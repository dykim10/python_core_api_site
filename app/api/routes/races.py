"""
대회 정보 CRUD 라우터 (app/api/routes/races.py)

review.races 테이블의 대회 데이터를 조회·저장한다.
REVIEW(Laravel) 내부에서 호출하며, 크롤링 결과 upsert 도 이 라우터를 통해 처리한다.

[엔드포인트]
  GET  /api/races/
    활성화된 대회 목록 반환 (is_active=true, race_date 내림차순)
    쿼리 파라미터: limit (기본 20)

  GET  /api/races/crawl-wa-labels?year=2026
    Wikipedia에서 WA 라벨 공인 대회 목록 수집 (CC BY-SA)
    year 기본값: 현재 연도

  POST /api/races/sync?year=2024
    Wikipedia WA 라벨 대회를 review.races에 upsert
    - 이름 일치 시 wa_label / is_certified / source 업데이트
    - 미일치 시 신규 INSERT (is_certified=true)
    - 반환: {year, total, inserted, updated, skipped}

  GET  /api/races/{race_id}
    대회 단건 조회 — 없으면 HTTP 404

  POST /api/races/
    대회 신규 등록 (dict payload 자유 형식)
    race_date 가 date 타입이면 문자열로 변환 후 저장
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException
from app.core.database import review_db
from app.services.race_crawler import crawl_wa_label_races, parse_wa_race_date, translate_race_names_to_korean
from typing import List

router = APIRouter(prefix="/api/races", tags=["races"])


@router.get("/crawl-wa-labels", response_model=List[dict])
def get_wa_label_races(year: int = 0):
    """Wikipedia에서 WA 라벨 공인 대회 목록을 수집해 반환한다.
    year 미지정 시 현재 연도 사용.
    """
    target_year = year if year > 0 else datetime.now().year
    races = crawl_wa_label_races(target_year)
    if not races:
        raise HTTPException(status_code=404, detail=f"{target_year}년 WA 라벨 대회 목록을 가져올 수 없습니다.")
    return races


@router.get("/", response_model=List[dict])
def get_races(limit: int = 20):
    res = (
        review_db()
        .table("races")
        .select("*")
        .eq("is_active", True)
        .order("race_date", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


@router.post("/sync", response_model=dict)
def sync_wa_label_races(year: int = 0):
    """Wikipedia WA 라벨 대회를 review.races에 upsert한다.

    이름 완전 일치(대소문자 무관) → UPDATE (wa_label / is_certified / source)
    미일치 → INSERT (신규 공인 대회, is_certified=true)
    한/영 이름 불일치 대회는 신규 INSERT 후 관리자가 수동 병합한다.
    """
    target_year = year if year > 0 else datetime.now().year
    wa_races = crawl_wa_label_races(target_year)
    if not wa_races:
        raise HTTPException(status_code=404, detail=f"{target_year}년 WA 라벨 대회를 가져올 수 없습니다.")

    # 영문명 → 한국어 번역 (name_en 보존, name 교체)
    wa_races = translate_race_names_to_korean(wa_races)

    existing_res = review_db().table("races").select("id,name,wa_label").execute()
    existing_by_name = {
        r["name"].lower(): r
        for r in (existing_res.data or [])
    }

    inserted = updated = skipped = 0

    for race in wa_races:
        cert_payload = {
            "wa_label":    race["wa_label"],
            "is_certified": True,
            "source":      "world_athletics",
            "source_url":  race.get("source_url", ""),
        }
        existing = existing_by_name.get(race["name"].lower())

        if existing:
            if existing.get("wa_label") == race["wa_label"]:
                skipped += 1
                continue
            review_db().table("races").update(cert_payload).eq("id", existing["id"]).execute()
            updated += 1
        else:
            review_db().table("races").insert({
                "name":        race["name"],
                "name_en":     race.get("name_en", ""),
                "city":        race.get("city", ""),
                "race_date":   parse_wa_race_date(race.get("date", ""), target_year),
                "is_active":   True,
                "status":      "active",
                **cert_payload,
            }).execute()
            inserted += 1

    return {
        "year":     target_year,
        "total":    len(wa_races),
        "inserted": inserted,
        "updated":  updated,
        "skipped":  skipped,
    }


@router.get("/{race_id}", response_model=dict)
def get_race(race_id: int):
    res = (
        review_db()
        .table("races")
        .select("*")
        .eq("id", race_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="대회 없음")
    return res.data


@router.post("/", response_model=dict)
def create_race(payload: dict):
    if "race_date" in payload:
        payload["race_date"] = str(payload["race_date"])
    res = review_db().table("races").insert(payload).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="저장 실패")
    return res.data[0]
