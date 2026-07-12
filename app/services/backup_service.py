"""
DB 백업 서비스 (app/services/backup_service.py)

Supabase service_role 키로 전체 데이터를 JSON 덤프 → gzip 압축 → S3 저장.
별도 DB 비밀번호나 postgresql-client 설치 없이 기존 .env 설정만으로 동작한다.

[백업 구조]
  S3: backups/{YYYY}/{MM}/{DD}/data_{YYYYMMDD_HHMMSS}.json.gz
  보관: retention_days 일 (기본 7일)

[복원 절차]
  1. php artisan migrate          → 스키마 복구
  2. POST /api/backup/restore     → JSON 데이터 복원 (또는 수동 import)

[백업 대상 테이블]
  public  : users, crews, branches, groups, generations, regions
  review  : races, reviews, race_weather
  crew    : running_logs, events, event_scores, user_goals, event_registrations,
            event_groups, event_group_members, event_fixed_submissions,
            users_detail, notices, notice_reads, boards, board_comments,
            bug_reports, photo_galleries, meeting_minutes, applications,
            application_forms, sms_logs, settings, user_generations,
            google_forms
"""
import gzip
import io
import json
import logging
from datetime import datetime, timedelta, timezone

import boto3
import pytz

from app.core.config import settings
from app.core.database import get_service_supabase

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

# 스키마별 백업 대상 테이블
BACKUP_TABLES: dict[str, list[str]] = {
    "public": [
        "users", "crews", "branches", "groups", "generations", "regions",
    ],
    "review": [
        "races", "reviews", "race_weather",
    ],
    "crew": [
        "running_logs", "events", "event_scores", "user_goals",
        "event_registrations", "event_groups", "event_group_members",
        "event_fixed_submissions", "users_detail", "notices", "notice_reads",
        "boards", "board_comments", "bug_reports", "photo_galleries",
        "meeting_minutes", "applications", "application_forms",
        "sms_logs", "settings", "user_generations",
        "google_forms",
    ],
}

PAGE_SIZE = 1000  # 한 번에 가져올 행 수


def run_backup() -> dict:
    """
    전체 백업 실행. 스케줄러 및 수동 트리거 API에서 호출.
    반환값: { success, s3_key, size_mb, elapsed_sec, tables, error }
    """
    import time
    start = time.time()

    if not settings.aws_bucket:
        return _error("AWS_BUCKET 이 .env 에 설정되지 않았습니다.")
    if not settings.supabase_service_role_key:
        return _error("SUPABASE_SERVICE_ROLE_KEY 가 .env 에 설정되지 않았습니다.")

    now_kst   = datetime.now(KST)
    timestamp = now_kst.strftime("%Y%m%d_%H%M%S")
    s3_key    = f"backups/{now_kst.strftime('%Y/%m/%d')}/data_{timestamp}.json.gz"

    dump      = {}
    table_counts: dict[str, int] = {}

    try:
        client = get_service_supabase()

        for schema, tables in BACKUP_TABLES.items():
            dump[schema] = {}
            db = client if schema == "public" else client.schema(schema)

            for table in tables:
                try:
                    rows = _fetch_all(db, table)
                    dump[schema][table] = rows
                    table_counts[f"{schema}.{table}"] = len(rows)
                except Exception as e:
                    # 테이블이 없거나 권한 없음 → 건너뛰고 계속 진행
                    logger.warning(f"[백업] {schema}.{table} 건너뜀: {e}")
                    table_counts[f"{schema}.{table}"] = -1

        gz_bytes = _gzip_json(dump)
        _upload_to_s3(s3_key, gz_bytes)

    except Exception as e:
        logger.error(f"[백업 실패] {e}")
        return _error(str(e))

    deleted  = _cleanup_old_backups()
    elapsed  = round(time.time() - start, 1)
    size_mb  = round(len(gz_bytes) / 1024 / 1024, 2)

    logger.info(f"[백업 완료] {s3_key} | {size_mb}MB | {elapsed}s | 삭제 {deleted}건")

    from app.services.system_log_service import db_log
    db_log("backup", "info", f"백업 완료 {s3_key}", {
        "s3_key": s3_key,
        "size_mb": size_mb,
        "elapsed_sec": elapsed,
        "deleted_old": deleted,
        "table_count": len(table_counts),
    })

    return {
        "success":     True,
        "s3_key":      s3_key,
        "size_mb":     size_mb,
        "elapsed_sec": elapsed,
        "tables":      table_counts,
        "deleted_old": deleted,
    }


def list_backups(limit: int = 30) -> list[dict]:
    """S3에서 최근 백업 목록 반환."""
    s3       = _s3_client()
    response = s3.list_objects_v2(Bucket=settings.aws_bucket, Prefix="backups/")
    items    = response.get("Contents", [])
    items.sort(key=lambda x: x["LastModified"], reverse=True)

    return [
        {
            "key":           item["Key"],
            "size_mb":       round(item["Size"] / 1024 / 1024, 2),
            "last_modified": item["LastModified"].astimezone(KST).strftime("%Y-%m-%d %H:%M KST"),
        }
        for item in items[:limit]
    ]


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _fetch_all(db, table: str) -> list[dict]:
    """페이지네이션으로 테이블 전체 데이터 조회."""
    all_rows: list[dict] = []
    offset = 0

    while True:
        resp = db.table(table).select("*").range(offset, offset + PAGE_SIZE - 1).execute()
        rows = resp.data or []
        all_rows.extend(rows)
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return all_rows


def _gzip_json(data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        gz.write(payload)
    return buf.getvalue()


def _upload_to_s3(key: str, data: bytes) -> None:
    _s3_client().put_object(
        Bucket=settings.aws_bucket,
        Key=key,
        Body=data,
        ContentType="application/gzip",
    )


def _cleanup_old_backups() -> int:
    cutoff   = datetime.now(timezone.utc) - timedelta(days=settings.backup_retention_days)
    s3       = _s3_client()
    response = s3.list_objects_v2(Bucket=settings.aws_bucket, Prefix="backups/")
    old_keys = [
        {"Key": item["Key"]}
        for item in response.get("Contents", [])
        if item["LastModified"] < cutoff
    ]
    if old_keys:
        s3.delete_objects(Bucket=settings.aws_bucket, Delete={"Objects": old_keys})
    return len(old_keys)


def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def _error(msg: str) -> dict:
    logger.error(f"[백업 실패] {msg}")
    from app.services.system_log_service import db_log
    db_log("backup", "error", msg[:500], {})
    return {"success": False, "error": msg}
