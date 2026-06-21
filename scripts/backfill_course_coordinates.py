"""
review.race_courses 기존 row 좌표(coordinates/markers) 백필 스크립트

대상: coordinates IS NULL AND gpx_url IS NOT NULL인 row (이미 S3에 실 GPX가
업로드된 코스만 — gpx_url 스텁만 있고 S3 오브젝트가 없는 row는 GET 실패로
자동 skip된다).

실행 전 체크리스트:
  [ ] pilot edition에 Admin GPX 실업로드 완료 (스텁만으로는 백필 불가)
  [ ] core-api/.env AWS + Supabase service role 설정 확인
  [ ] 드라이런(--dry-run) 으로 먼저 대상 row 확인

실행 방법:
  python scripts/backfill_course_coordinates.py                    # 전체 백필
  python scripts/backfill_course_coordinates.py --dry-run           # 대상만 출력
  python scripts/backfill_course_coordinates.py --edition-id 305    # 특정 edition만
"""
import sys
import os
import argparse
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3

from app.core.config import settings
from app.core.database import review_db
from app.services.gpx_service import parse_gpx_bytes


def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def _fetch_gpx_bytes(s3, gpx_url: str) -> bytes:
    key = urlparse(gpx_url).path.lstrip("/")
    obj = s3.get_object(Bucket=settings.aws_bucket, Key=key)
    return obj["Body"].read()


def backfill(dry_run: bool = False, edition_id: int | None = None) -> None:
    mode = "[DRY-RUN]" if dry_run else "[LIVE]"
    print(f"{mode} race_courses 좌표 백필 시작\n")

    db = review_db()
    s3 = _s3_client()

    query = (
        db.table("race_courses")
        .select("id, race_edition_id, course_type, gpx_url")
        .is_("coordinates", "null")
        .not_.is_("gpx_url", "null")
    )
    if edition_id is not None:
        query = query.eq("race_edition_id", edition_id)

    rows = query.execute().data or []

    total = len(rows)
    updated = 0
    skipped = 0
    failed = 0

    for row in rows:
        course_id = row["id"]
        label = f"id={course_id} edition={row['race_edition_id']} type={row['course_type']}"

        try:
            gpx_bytes = _fetch_gpx_bytes(s3, row["gpx_url"])
        except Exception as e:
            print(f"  [SKIP] {label} — S3 다운로드 실패 (스텁-only로 추정): {e}")
            skipped += 1
            continue

        parsed = parse_gpx_bytes(gpx_bytes)
        if not parsed or not parsed.get("coordinates"):
            print(f"  [SKIP] {label} — GPX 파싱 실패 또는 좌표 없음")
            skipped += 1
            continue

        n_coords = len(parsed["coordinates"])
        n_markers = len(parsed["markers"])

        if dry_run:
            print(f"  [DRY] {label}  coordinates={n_coords}점  markers={n_markers}점")
        else:
            db.table("race_courses").update({
                "coordinates": parsed["coordinates"],
                "markers": parsed["markers"],
            }).eq("id", course_id).execute()
            print(f"  [OK]  {label}  coordinates={n_coords}점  markers={n_markers}점")

        updated += 1

    print(f"\n{mode} 완료")
    print(f"  대상: {total}건 | 처리: {updated}건 | 스킵: {skipped}건 | 실패: {failed}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="race_courses coordinates/markers 백필")
    parser.add_argument("--dry-run", action="store_true", help="DB 변경 없이 대상 row와 예상 포인트 수만 출력")
    parser.add_argument("--edition-id", type=int, default=None, help="특정 race_edition_id만 처리")
    args = parser.parse_args()

    backfill(dry_run=args.dry_run, edition_id=args.edition_id)
