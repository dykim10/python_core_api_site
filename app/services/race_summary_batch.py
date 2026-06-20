"""
대회 종합 AI 요약 배치 (TASK-REMODEL-14)

리뷰 CRUD 시 즉시 재생성하지 않고, ai_race_summary._meta.dirty 플래그가
설정된 race만 1일 1회 배치에서 처리한다.
"""
import json
import logging

import anthropic

from app.core.config import settings
from app.core.database import review_db
from app.core.model_config import model_for

logger = logging.getLogger(__name__)


def _summarize_one(race: dict, reviews: list[str], avg_rating: float, live: bool) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    reviews_text = "\n\n".join(f"[리뷰 {i + 1}] {r}" for i, r in enumerate(reviews))

    prompt = f"""다음은 마라톤/러닝 대회 '{race['name']}'에 참가한 {len(reviews)}명의 후기입니다.
평균 평점: {avg_rating:.1f} / 5.0

--- 후기 목록 ---
{reviews_text}
---

위 후기들을 종합 분석하여 아래 JSON 형식으로만 응답해주세요 (다른 텍스트 금지):
{{
  "summary": "전체 후기를 종합한 3~5문장의 대회 평가 요약 (한국어).",
  "positives": ["칭찬 포인트1", "포인트2"],
  "negatives": ["아쉬운 포인트1"],
  "keywords": ["키워드1", "키워드2", "키워드3"]
}}"""

    response = client.messages.create(
        model=model_for("race_summarize"),
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(cleaned)
    parsed["_meta"] = {"dirty": False, "batch": True}
    return parsed


def batch_pending_race_summaries(live: bool = True) -> dict:
    db = review_db(live=live)
    races_res = db.table("races").select("id, name, ai_race_summary").eq("is_active", True).execute()
    races = races_res.data or []

    processed = skipped = failed = 0

    for race in races:
        summary = race.get("ai_race_summary") or {}
        if isinstance(summary, str):
            try:
                summary = json.loads(summary)
            except json.JSONDecodeError:
                summary = {}

        meta = summary.get("_meta") or {}
        if not meta.get("dirty"):
            skipped += 1
            continue

        editions_res = db.table("race_editions").select("id").eq("race_id", race["id"]).execute()
        edition_ids = [e["id"] for e in (editions_res.data or [])]
        if not edition_ids:
            skipped += 1
            continue

        reviews_res = (
            db.table("reviews")
            .select("content, rating")
            .in_("race_edition_id", edition_ids)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        rows = reviews_res.data or []
        if not rows:
            db.table("races").update({"ai_race_summary": {"_meta": {"dirty": False}}}).eq("id", race["id"]).execute()
            skipped += 1
            continue

        contents = [r["content"] for r in rows if r.get("content")]
        ratings = [r["rating"] for r in rows if r.get("rating") is not None]
        avg = sum(ratings) / len(ratings) if ratings else 0.0

        try:
            result = _summarize_one(race, contents, avg, live)
            db.table("races").update({"ai_race_summary": result}).eq("id", race["id"]).execute()
            processed += 1
            logger.info(f"[RaceSummaryBatch] race_id={race['id']} 완료")
        except Exception as e:
            failed += 1
            logger.error(f"[RaceSummaryBatch] race_id={race['id']} 실패: {e}")

    return {"processed": processed, "skipped": skipped, "failed": failed}
