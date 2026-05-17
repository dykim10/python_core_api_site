import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from openai import OpenAI
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

    client = OpenAI(api_key=settings.openai_api_key)

    prompt = f"""다음은 마라톤/러닝 대회 참가 후기입니다.
대회명: {req.race_name}
후기: {req.content}

아래 두 가지를 JSON 형식으로만 응답해주세요 (다른 텍스트 금지):
{{
  "summary": "후기를 2~3문장으로 요약 (한국어)",
  "sentiment": "positive 또는 negative 또는 neutral 중 하나"
}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()
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
