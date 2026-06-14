#!/usr/bin/env python3
"""
sync_review.py — REVIEW LIVE → LOCAL 단방향 동기화

방향: LIVE ──▶ LOCAL  (역방향 절대 없음)

[.env 필수 변수]
  SUPABASE_URL                로컬 Supabase REST URL
  SUPABASE_SERVICE_ROLE_KEY   로컬 Service Role Key
  SUPABASE_LIVE_URL               LIVE Supabase REST URL
  SUPABASE_LIVE_SERVICE_ROLE_KEY  LIVE Service Role Key

[실행 예시]
  python sync_review.py             # 전체 동기화
  python sync_review.py --dry-run   # 읽기만 (로컬 변경 없음)
  python sync_review.py --check     # 연결 진단만
  python sync_review.py --tables review.races,review.reviews
"""
import argparse
import os
import sys
import time

from dotenv import load_dotenv
from _sync_core import sync, check_connections, make_clients

load_dotenv()

# ── 동기화 테이블 목록 (FK 의존성 순서) ──────────────────────────────────────
SYNC_TABLES: list[tuple[str, str]] = [
    # public (races / reviews 의 user_id FK 대비)
    ("public", "users"),
    # review 스키마
    ("review", "races"),              # 대회 정보
    ("review", "race_editions"),      # 대회 개최 이력 (races 의존)
    ("review", "race_weather"),       # 대회 날씨 (races 의존)
    ("review", "reviews"),            # 참가 후기 (races + users 의존)
    ("review", "completion_records"), # 완주 기록 (race_editions + users 의존)
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="REVIEW LIVE → LOCAL 단방향 동기화",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="읽기만 수행 (로컬 DB 변경 없음)")
    parser.add_argument("--check",   action="store_true", help="연결 진단만 수행")
    parser.add_argument("--tables",  help="쉼표 구분 (예: review.races,review.reviews)")
    args = parser.parse_args()

    if args.check:
        print("\n연결 및 키 진단\n" + "-" * 50)
        ok = check_connections("SUPABASE_LIVE_URL", "SUPABASE_LIVE_SERVICE_ROLE_KEY")
        print("-" * 50)
        print("진단 완료 — 문제 없음" if ok else "문제가 있습니다. 위 내용 확인 필요")
        sys.exit(0 if ok else 1)

    live, local = make_clients("SUPABASE_LIVE_URL", "SUPABASE_LIVE_SERVICE_ROLE_KEY")

    targets = SYNC_TABLES
    if args.tables:
        targets = []
        for spec in args.tables.split(","):
            parts = spec.strip().split(".")
            if len(parts) == 2:
                targets.append((parts[0], parts[1]))
            else:
                print(f"형식 오류 (schema.table 필요): {spec}")

    mode = " [DRY-RUN]" if args.dry_run else ""
    print(f"\nREVIEW LIVE -> LOCAL 동기화 시작{mode}")
    print(f"  LIVE : {os.getenv('SUPABASE_LIVE_URL')}")
    print(f"  LOCAL: {os.getenv('SUPABASE_URL')}")
    print(f"  대상 : {len(targets)}개 테이블\n")

    t_start        = time.time()
    total, errors  = sync(live, local, targets, dry_run=args.dry_run)
    elapsed        = time.time() - t_start

    print(f"\n{'-' * 60}")
    if args.dry_run:
        print(f"DRY-RUN 완료 -- 총 {total}건 확인 / {elapsed:.1f}초 (로컬 변경 없음)")
    else:
        print(f"동기화 완료 -- 총 {total}건 처리 / {elapsed:.1f}초")
    if errors:
        print(f"오류 {len(errors)}건:")
        for label, err in errors:
            print(f"  {label}: {err}")
    print()


if __name__ == "__main__":
    main()
