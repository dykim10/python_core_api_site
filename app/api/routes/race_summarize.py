"""
대회 종합 분석 라우터 (app/api/routes/race_summarize.py)

REVIEW(Laravel) 에서 대회 상세 페이지의 AI 종합 분석 기능에서 호출한다.
여러 개의 후기를 한 번에 받아 claude-opus-4-8 로 대회 전체를 평가한다.

POST /api/races/summarize
  요청 : {
    "race_name"  : "대회명",
    "reviews"    : ["후기1", "후기2", ...],
    "avg_rating" : 4.2,
    "total_count": 15
  }
  응답 : {
    "summary"  : "종합 평가 3~5문장",
    "positives": ["칭찬 포인트1", ...],
    "negatives": ["아쉬운 포인트1", ...],
    "keywords" : ["키워드1", ..., "키워드5"]
  }

[프롬프트 구성]
  리뷰 목록을 "[리뷰 1] text", "[리뷰 2] text" 형식으로 번호를 붙여 전달.
  positives / negatives 는 실제 후기에서 언급된 내용만 포함하도록 지시.
  없는 항목은 빈 배열로 반환하도록 지시.
"""
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import anthropic
from app.core.config import settings
from app.core.model_config import model_for

router = APIRouter(prefix="/api/races", tags=["race-summarize"])


class RaceSummarizeRequest(BaseModel):
    race_name: str
    reviews: list[str]       # 리뷰 내용 목록
    avg_rating: float = 0.0
    total_count: int = 0


class RaceSummarizeResponse(BaseModel):
    summary: str             # 종합 요약 (3~5문장)
    positives: list[str]     # 주요 긍정 포인트
    negatives: list[str]     # 주요 개선 포인트
    keywords: list[str]      # 대표 키워드


@router.post("/summarize", response_model=RaceSummarizeResponse)
def summarize_race(req: RaceSummarizeRequest):
    if not req.reviews:
        raise HTTPException(status_code=422, detail="리뷰가 없습니다.")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    reviews_text = "\n\n".join(
        [f"[리뷰 {i+1}] {r}" for i, r in enumerate(req.reviews)]
    )

    prompt = f"""다음은 마라톤/러닝 대회 '{req.race_name}'에 참가한 {req.total_count}명의 후기입니다.
평균 평점: {req.avg_rating:.1f} / 5.0

--- 후기 목록 ---
{reviews_text}
---

위 후기들을 종합 분석하여 아래 JSON 형식으로만 응답해주세요 (다른 텍스트 금지):
{{
  "summary": "전체 후기를 종합한 3~5문장의 대회 평가 요약 (한국어). 참가자들의 전반적인 경험을 객관적으로 서술.",
  "positives": ["참가자들이 공통으로 칭찬한 포인트 1", "포인트 2", "포인트 3"],
  "negatives": ["참가자들이 공통으로 아쉬워한 포인트 1", "포인트 2"],
  "keywords": ["대표 키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]
}}

positives/negatives는 실제 후기에 언급된 내용만 포함하고, 없으면 빈 배열로 반환하세요."""

    try:
        response = client.messages.create(
            model=model_for("race_summarize"),
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)

        return RaceSummarizeResponse(
            summary=parsed.get("summary", ""),
            positives=parsed.get("positives", []),
            negatives=parsed.get("negatives", []),
            keywords=parsed.get("keywords", []),
        )
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI 응답 파싱 실패: {raw}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
