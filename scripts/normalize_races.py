"""
review.races distances / status 일괄 정규화 업데이트
실행: python scripts/normalize_races.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.services.race_crawler import _normalize_distances, _compute_status
from supabase import create_client

PAGE_SIZE = 200


def main():
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    db = client.schema("review")

    all_races = []
    offset = 0
    while True:
        res = db.table("races").select("id,distances,race_date,reg_start,reg_end,status,source") \
            .range(offset, offset + PAGE_SIZE - 1).execute()
        batch = res.data or []
        all_races.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    print(f"총 {len(all_races)}건 조회")

    updated, skipped, errors = 0, 0, 0

    for race in all_races:
        raw_dist = race.get("distances") or []
        new_dist = _normalize_distances(raw_dist)
        new_status = _compute_status(race)

        if new_dist == raw_dist and new_status == race.get("status"):
            skipped += 1
            continue

        try:
            db.table("races").update({
                "distances": new_dist,
                "status": new_status,
            }).eq("id", race["id"]).execute()
            updated += 1
            print(f"  [OK] id={race['id']:5d}  {str(raw_dist):40s} → {new_dist}  ({race.get('status')} → {new_status})")
        except Exception as e:
            errors += 1
            print(f"  [오류] id={race['id']}: {e}")

    print(f"\n완료: 업데이트 {updated}건 / 스킵 {skipped}건 / 오류 {errors}건")


if __name__ == "__main__":
    main()
