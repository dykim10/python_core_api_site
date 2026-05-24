"""
Vision AI 클라이언트 (app/services/claude_client.py)

이미지를 Vision AI 모델에 전달해 텍스트 응답을 받는 공통 유틸.
현재는 OpenAI GPT-4o 를 사용하며, 향후 Claude Vision API 로 전환 예정.

[함수]
  get_openai_client() → OpenAI
    settings.openai_api_key 로 OpenAI 클라이언트 생성

  invoke_with_image(image_bytes, media_type, prompt) → str
    이미지를 Base64 인코딩해 data URL 형식으로 전달한다.
    모델: gpt-4o / max_tokens: 1024
    응답 텍스트를 그대로 반환하며, JSON 파싱은 호출부에서 처리한다.

[데이터 URL 형식]
  "data:{media_type};base64,{base64_string}"
  GPT-4o 는 이 형식의 인라인 이미지를 직접 읽을 수 있다.

[호출처]
  parse_image.py → PARSE_PROMPT 로 러닝 기록 수치 추출
"""
import base64
from openai import OpenAI
from app.core.config import settings


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def invoke_with_image(image_bytes: bytes, media_type: str, prompt: str) -> str:
    client = get_openai_client()
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_data}",
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
        max_tokens=1024,
    )

    return response.choices[0].message.content
