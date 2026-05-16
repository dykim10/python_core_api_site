"""
review.races distances 데이터 현황 분석 + 정규화 미리보기 (읽기 전용)
실행: python scripts/analyze_distances.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
from app.core.config import settings
from app.services.race_crawler import _normalize_distances
from supabase import create_client

PAGE_SIZE = 200


def main():
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    db = client.schema("review")

    all_races = []
    offset = 0
    while True:
        res = db.table("races").select("id,name,distances,source") \
            .range(offset, offset + PAGE_SIZE - 1).execute()
        batch = res.data or []
        all_races.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    print(f"총 {len(all_races)}건\n")

    # 변환 전/후 비교 (배열 패턴 기준)
    before_after: dict[str, str] = {}
    changed_cases = []
    unchanged_cases = []

    for race in all_races:
        raw = race.get("distances") or []
        normalized = _normalize_distances(raw)
        key_before = str(raw)
        key_after = str(normalized)

        if key_before not in before_after:
            before_after[key_before] = key_after

        if raw != normalized:
            changed_cases.append({
                "id": race["id"],
                "name": race["name"],
                "before": raw,
                "after": normalized,
                "source": race["source"],
            })

    print(f"=== 변환이 발생하는 패턴 ({len([v for k,v in before_after.items() if k != v])}종) ===")
    for before, after in sorted(before_after.items()):
        if before != after:
            print(f"  {before}")
            print(f"    → {after}")

    print(f"\n=== 변환 없는 패턴 ({len([v for k,v in before_after.items() if k == v])}종) ===")
    for before, after in sorted(before_after.items()):
        if before == after:
            print(f"  {before}")

    print(f"\n=== 개별 레코드 변환 대상 ({len(changed_cases)}건) ===")
    for c in changed_cases:
        print(f"  id={c['id']:5d}  {str(c['before']):45s} → {str(c['after'])}")

    print(f"\n변환 대상: {len(changed_cases)}건 / 변환 없음: {len(all_races) - len(changed_cases)}건")


if __name__ == "__main__":
    main()
