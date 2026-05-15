import boto3
import json
import base64
from app.core.config import settings


def get_bedrock_client():
    return boto3.client(
        service_name="bedrock-runtime",
        region_name="us-east-1",
    )


def invoke_claude(messages: list, max_tokens: int = 1024) -> str:
    client = get_bedrock_client()
    model_id = "us.anthropic.claude-sonnet-4-5"

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": messages,
    }

    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
    )

    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


def invoke_claude_with_image(image_bytes: bytes, media_type: str, prompt: str) -> str:
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    messages = [
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
    ]

    return invoke_claude(messages)
