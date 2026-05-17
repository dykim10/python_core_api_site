import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from openai import OpenAI
from app.core.config import settings

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

    client = OpenAI(api_key=settings.openai_api_key)

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
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()
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
