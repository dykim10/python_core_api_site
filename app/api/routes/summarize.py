"""
리뷰 AI 요약 라우터 (app/api/routes/summarize.py)

REVIEW(Laravel) 에서 개별 후기를 AI 요약할 때 호출한다.
claude-opus-4-8 로 후기를 2~3문장으로 요약하고 감성을 분류한다.

POST /api/summarize
  요청 : {"content": "후기 텍스트", "race_name": "대회명(선택)"}
  응답 : {"summary": "요약 텍스트", "sentiment": "positive|negative|neutral"}

[AI 응답 처리]
  JSON 외에 마크다운 코드 블록(```json)을 포함해 응답할 수 있으므로
  removeprefix / removesuffix 로 마커를 제거한 뒤 json.loads 한다.
  sentiment 값이 세 가지 중 하나가 아니면 "neutral" 로 fallback.
"""
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import anthropic
from app.core.config import settings

router = APIRouter(prefix="/api", tags=["summarize"])


class SummarizeRequest(BaseModel):
    content: str
    race_name: str = ""


class SummarizeResponse(BaseModel):
    summary: str
    sentiment: str  # positive / negative / neutral


@router.post("/summarize", response_model=SummarizeResponse)
def summarize_review(req: SummarizeRequest):
    if not req.content.strip():
        raise HTTPException(status_code=422, detail="content가 비어 있습니다.")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    prompt = f"""다음은 마라톤/러닝 대회 참가 후기입니다.
대회명: {req.race_name}
후기: {req.content}

아래 두 가지를 JSON 형식으로만 응답해주세요 (다른 텍스트 금지):
{{
  "summary": "후기를 2~3문장으로 요약 (한국어)",
  "sentiment": "positive 또는 negative 또는 neutral 중 하나"
}}"""

    try:
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)

        sentiment = parsed.get("sentiment", "neutral").lower()
        if sentiment not in ("positive", "negative", "neutral"):
            sentiment = "neutral"

        return SummarizeResponse(
            summary=parsed.get("summary", ""),
            sentiment=sentiment,
        )
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI 응답 파싱 실패: {raw}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
