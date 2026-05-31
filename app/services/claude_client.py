"""
Vision AI 클라이언트 (app/services/claude_client.py)

이미지를 Claude Vision API 에 전달해 텍스트 응답을 받는 공통 유틸.
모델: claude-opus-4-8 / max_tokens: 1024

[함수]
  invoke_with_image(image_bytes, media_type, prompt) → str
    이미지를 Base64 인코딩해 Anthropic 이미지 소스 형식으로 전달한다.
    응답 텍스트를 그대로 반환하며, JSON 파싱은 호출부에서 처리한다.

[호출처]
  parse_image.py → PARSE_PROMPT 로 러닝 기록 수치 추출
"""
import base64
import anthropic
from app.core.config import settings


def invoke_with_image(image_bytes: bytes, media_type: str, prompt: str) -> str:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )

    return response.content[0].text
