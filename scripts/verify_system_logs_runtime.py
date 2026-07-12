"""CORE/REVIEW system_logs 런타임 검증 (§9 V4/V5/V6, §11). 실행 후 삭제 가능."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED


def _header(title: str) -> None:
    print(f"\n=== {title} ===")


def verify_db_log_insert() -> bool:
    """§11: CORE public_db(live=True) -> system_logs insert."""
    _header("S11 PostgREST db_log insert")
    from app.core.database import public_db
    from app.services.system_log_service import db_log

    marker = f"verify-{uuid.uuid4().hex[:8]}"
    db_log("backup", "info", f"PostgREST verify {marker}", {"verify": True, "marker": marker})

    rows = (
        public_db(live=True)
        .table("system_logs")
        .select("id, source, category, level, message, context")
        .ilike("message", f"%{marker}%")
        .execute()
        .data
        or []
    )
    if not rows:
        print("FAIL: insert 후 조회 0건 — PostgREST 스키마 캐시 또는 GRANT 확인 필요")
        return False

    row = rows[0]
    ok = (
        row.get("source") == "core"
        and row.get("category") == "backup"
        and row.get("level") == "info"
        and row.get("context", {}).get("marker") == marker
    )
    print(f"{'PASS' if ok else 'FAIL'}: id={row.get('id')} source={row.get('source')} category={row.get('category')}")
    return ok


def verify_scheduler_listener() -> bool:
    """§9 V4: APScheduler 리스너 ERROR → scheduler/error + scheduled_run_time."""
    _header("S9 V4 APScheduler listener ERROR")
    from app.core.database import public_db
    from app.core.scheduler import SERVICE_SUMMARY_JOBS, _job_listener

    job_id = f"verify_job_{uuid.uuid4().hex[:6]}"
    run_time = datetime.now(timezone.utc)
    event = SimpleNamespace(
        code=EVENT_JOB_ERROR,
        job_id=job_id,
        exception=RuntimeError("V4 검증 테스트"),
        scheduled_run_time=run_time,
    )
    _job_listener(event)

    rows = (
        public_db(live=True)
        .table("system_logs")
        .select("id, category, level, message, context")
        .ilike("message", f"%{job_id}%")
        .execute()
        .data
        or []
    )
    if not rows:
        print("FAIL: scheduler error 로그 없음")
        return False

    row = rows[0]
    ctx = row.get("context") or {}
    ok = (
        row.get("category") == "scheduler"
        and row.get("level") == "error"
        and ctx.get("job_id") == job_id
        and bool(ctx.get("scheduled_run_time"))
    )
    print(f"{'PASS' if ok else 'FAIL'}: message={row.get('message')!r} context={ctx}")

    # SERVICE_SUMMARY EXECUTED 생략 확인
    _header("S9 V4 SERVICE_SUMMARY EXECUTED skip")
    summary_job = next(iter(SERVICE_SUMMARY_JOBS))
    exec_event = SimpleNamespace(
        code=EVENT_JOB_EXECUTED,
        job_id=summary_job,
        scheduled_run_time=run_time,
    )
    before = (
        public_db(live=True)
        .table("system_logs")
        .select("id", count="exact")
        .ilike("message", f"%{summary_job} 성공%")
        .execute()
    )
    before_count = before.count or 0
    _job_listener(exec_event)
    after = (
        public_db(live=True)
        .table("system_logs")
        .select("id", count="exact")
        .ilike("message", f"%{summary_job} 성공%")
        .execute()
    )
    after_count = after.count or 0
    skipped = after_count == before_count
    print(f"{'PASS' if skipped else 'FAIL'}: {summary_job} EXECUTED(info) 생략 — count {before_count} -> {after_count}")
    return ok and skipped


def verify_fastapi_500_handler() -> bool:
    """§9 V5: 미처리 500 → app_error + 한국어 응답."""
    _header("S9 V5 FastAPI 500 handler")
    from fastapi.testclient import TestClient

    # main import 시 scheduler lifespan 부담 — TestClient context manager
    from main import app

    route_path = f"/__verify-500-{uuid.uuid4().hex[:6]}"

    @app.get(route_path)
    def _verify_500():
        _ = 1 / 0  # noqa: F841

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(route_path)

    if resp.status_code != 500:
        print(f"FAIL: status={resp.status_code} body={resp.text}")
        return False

    body = resp.json()
    korean_ok = body.get("detail") == "서버 오류가 발생했습니다."
    print(f"{'PASS' if korean_ok else 'FAIL'}: response detail={body.get('detail')!r}")

    from app.core.database import public_db

    rows = (
        public_db(live=True)
        .table("system_logs")
        .select("id, category, level, context")
        .eq("category", "app_error")
        .eq("level", "error")
        .contains("context", {"path": route_path})
        .execute()
        .data
        or []
    )
    # contains may not work on all postgrest — fallback ilike on message
    if not rows:
        rows = (
            public_db(live=True)
            .table("system_logs")
            .select("id, category, level, context, message")
            .eq("category", "app_error")
            .order("id", desc=True)
            .limit(5)
            .execute()
            .data
            or []
        )
        rows = [r for r in rows if (r.get("context") or {}).get("path") == route_path]

    if not rows:
        print("FAIL: app_error 로그 없음")
        return False

    row = rows[0]
    ctx = row.get("context") or {}
    log_ok = ctx.get("exception") == "ZeroDivisionError" and ctx.get("path") == route_path
    print(f"{'PASS' if log_ok else 'FAIL'}: app_error context={ctx}")

    # 임시 라우트 제거
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != route_path]

    # HTTPException(404)는 app_error 미기록
    _header("S9 V5 HTTPException 404 excluded")
    with TestClient(app, raise_server_exceptions=False) as client:
        before = (
            public_db(live=True)
            .table("system_logs")
            .select("id", count="exact")
            .eq("category", "app_error")
            .execute()
            .count
            or 0
        )
        client.get("/__no-such-route-for-verify-404__")
        after = (
            public_db(live=True)
            .table("system_logs")
            .select("id", count="exact")
            .eq("category", "app_error")
            .execute()
            .count
            or 0
        )
    excluded = before == after
    print(f"{'PASS' if excluded else 'FAIL'}: 404 후 app_error count {before} -> {after}")
    return korean_ok and log_ok and excluded


def main() -> int:
    from app.core.secrets_loader import load_secrets

    load_secrets()

    results = [
        ("S11 db_log insert", verify_db_log_insert()),
        ("S9 V4 scheduler listener", verify_scheduler_listener()),
        ("S9 V5 FastAPI 500", verify_fastapi_500_handler()),
    ]

    print("\n=== SUMMARY ===")
    failed = 0
    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
        if not ok:
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
