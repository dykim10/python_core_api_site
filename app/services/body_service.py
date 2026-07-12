"""
체성분(인바디) 파싱 + Fernet 암호화 CRUD (app/services/body_service.py)

- 인바디 이미지 → Claude Vision 파싱 (DB 저장 없음)
- body_records INSERT/SELECT (암호화/복호화는 CORE 내부 전용)
"""
import json
import logging
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

import boto3
from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.core.database import crew_db
from app.core.model_config import model_for
from app.services.claude_client import invoke_with_image
from app.utils.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/gif": "image/gif",
    "image/webp": "image/webp",
}

INBODY_PROMPT = """\
이 이미지는 인바디(InBody) 측정 결과입니다 (앱 캡처 또는 종이 결과지).
아래 항목을 JSON 형식으로만 응답하세요. 없는 항목은 null.

{
  "measured_at": "YYYY-MM-DDTHH:MM:SS",
  "year_in_image": true/false,
  "weight_kg": 숫자,
  "skeletal_muscle_kg": 숫자,
  "body_fat_kg": 숫자,
  "bmi": 숫자,
  "body_fat_percent": 숫자,
  "inbody_score": 정수,
  "changes": {
    "weight": 숫자 또는 null,
    "skeletal_muscle": 숫자 또는 null,
    "body_fat_percent": 숫자 또는 null
  }
}

[절대 추출 금지] 회원번호, 이름, 전화번호, 이메일 등 개인 식별 정보
JSON 외 텍스트 금지. 마크다운 백틱 금지.\
"""


def _normalize_measured_at(raw: str | None, year_in_image: bool = True) -> str | None:
    """CREW sanitizeRunDate + parse_image 규칙: 2년 이상 과거→올해, 미래→전년도."""
    if not raw:
        return None
    raw = str(raw).strip()
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    current_year = today.year

    if not re.search(r"\b\d{4}\b", raw):
        raw = f"{current_year}-{raw}"

    parsed = None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            parsed = datetime.strptime(raw[:19] if "T" in fmt else raw[:10], fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        return None

    if not year_in_image and parsed.year < current_year - 1:
        parsed = parsed.replace(year=current_year)

    if parsed.date() > today:
        parsed = parsed.replace(year=current_year - 1)

    tz = ZoneInfo("Asia/Seoul")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.isoformat()


def _parse_claude_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().removesuffix("```").strip()
    return json.loads(text)


async def read_image_upload(file: UploadFile) -> tuple[bytes, str]:
    media_type = SUPPORTED_TYPES.get(file.content_type or "")
    if not media_type:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 이미지 형식: {file.content_type}")
    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="이미지 크기는 10MB 이하여야 합니다.")
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    return image_bytes, media_type


def parse_inbody_image(image_bytes: bytes, media_type: str) -> dict[str, Any]:
    """Claude Vision으로 인바디 파싱 — DB 저장 없음."""
    raw = invoke_with_image(image_bytes, media_type, INBODY_PROMPT)
    try:
        parsed = _parse_claude_json(raw)
    except json.JSONDecodeError:
        try:
            parsed = _parse_claude_json(raw.replace("```json", "").replace("```", ""))
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=502, detail="인바디 이미지 파싱 결과를 해석할 수 없습니다.") from e

    year_in_image = bool(parsed.get("year_in_image", True))
    measured_at = _normalize_measured_at(parsed.get("measured_at"), year_in_image)

    return {
        "measured_at": measured_at,
        "weight_kg": parsed.get("weight_kg"),
        "skeletal_muscle_kg": parsed.get("skeletal_muscle_kg"),
        "body_fat_kg": parsed.get("body_fat_kg"),
        "bmi": parsed.get("bmi"),
        "body_fat_percent": parsed.get("body_fat_percent"),
        "inbody_score": parsed.get("inbody_score"),
        "changes": parsed.get("changes") or {},
    }


def _upload_inbody_to_s3(image_bytes: bytes, content_type: str) -> str:
    ext = content_type.split("/")[-1].replace("jpeg", "jpg")
    key = f"inbody/{uuid.uuid4().hex}.{ext}"
    s3 = boto3.client(
        "s3",
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    s3.put_object(
        Bucket=settings.aws_bucket,
        Key=key,
        Body=image_bytes,
        ContentType=content_type,
    )
    base = settings.aws_url.rstrip("/") if settings.aws_url else \
        f"https://{settings.aws_bucket}.s3.{settings.aws_default_region}.amazonaws.com"
    return f"{base}/{key}"


def _enc_num(value: float | int | None) -> str | None:
    if value is None:
        return None
    return encrypt(str(value))


def store_body_record(data: dict[str, Any]) -> dict[str, Any]:
    """체성분 Fernet 암호화 후 crew.body_records INSERT."""
    user_id = data["user_id"]
    measured_at = data["measured_at"]
    weight_kg = data["weight_kg"]

    row = {
        "user_id": user_id,
        "measured_at": measured_at,
        "weight_enc": _enc_num(weight_kg),
        "skeletal_muscle_enc": _enc_num(data.get("skeletal_muscle_kg")),
        "body_fat_kg_enc": _enc_num(data.get("body_fat_kg")),
        "bmi_enc": _enc_num(data.get("bmi")),
        "body_fat_percent_enc": _enc_num(data.get("body_fat_percent")),
        "inbody_score_enc": _enc_num(data.get("inbody_score")),
        "source": data.get("source", "manual"),
        "image_url": data.get("image_url"),
    }

    result = crew_db().table("body_records").insert(row).execute()
    inserted = (result.data or [{}])[0]
    logger.info(f"[Body] 저장 완료 user_id={user_id} id={inserted.get('id')}")
    return {"id": inserted.get("id"), "user_id": user_id, "measured_at": measured_at}


def _dec_num(enc: str | None) -> float | None:
    if not enc:
        return None
    plain = decrypt(enc)
    if plain is None:
        return None
    try:
        return float(plain)
    except ValueError:
        return None


def _dec_int(enc: str | None) -> int | None:
    val = _dec_num(enc)
    return int(val) if val is not None else None


def get_body_records(user_id: int, limit: int = 12) -> list[dict[str, Any]]:
    """복호화 후 평문 JSON 반환 (EC2 내부 통신)."""
    rows = (
        crew_db()
        .table("body_records")
        .select("id, user_id, measured_at, weight_enc, skeletal_muscle_enc, body_fat_kg_enc, bmi_enc, body_fat_percent_enc, inbody_score_enc, source, image_url, created_at")
        .eq("user_id", user_id)
        .order("measured_at", desc=True)
        .limit(limit)
        .execute()
        .data
    ) or []

    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "user_id": row["user_id"],
            "measured_at": row["measured_at"],
            "weight_kg": _dec_num(row.get("weight_enc")),
            "skeletal_muscle_kg": _dec_num(row.get("skeletal_muscle_enc")),
            "body_fat_kg": _dec_num(row.get("body_fat_kg_enc")),
            "bmi": _dec_num(row.get("bmi_enc")),
            "body_fat_percent": _dec_num(row.get("body_fat_percent_enc")),
            "inbody_score": _dec_int(row.get("inbody_score_enc")),
            "source": row.get("source"),
            "image_url": row.get("image_url"),
            "created_at": row.get("created_at"),
        })
    return result


def get_body_records_for_context(user_id: int, limit: int = 3) -> list[dict[str, Any]]:
    """코칭 컨텍스트용 — 최근 N건 숫자만."""
    records = get_body_records(user_id, limit=limit)
    return [
        {
            "measured_at": r["measured_at"],
            "weight_kg": r["weight_kg"],
            "body_fat_percent": r["body_fat_percent"],
            "skeletal_muscle_kg": r["skeletal_muscle_kg"],
        }
        for r in records
    ]
