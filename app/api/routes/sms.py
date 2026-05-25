"""
SMS 발송 API (app/api/routes/sms.py)

Solapi REST API를 통해 단체 문자를 발송한다.
인증: HMAC-SHA256 (apiKey + apiSecret → date + salt 서명)

엔드포인트:
  POST /api/sms/send  → phones 배열 + message 수신 → Solapi 일괄 발송
"""
import hmac
import hashlib
import uuid
import requests
from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.config import settings

router = APIRouter(prefix="/api/sms", tags=["sms"])


class SmsSendRequest(BaseModel):
    phones: list[str]
    message: str
    sender: str


def _solapi_auth_header(api_key: str, api_secret: str) -> str:
    date = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    salt = uuid.uuid4().hex
    signature = hmac.new(
        api_secret.encode('utf-8'),
        (date + salt).encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return f'HMAC-SHA256 apiKey={api_key}, date={date}, salt={salt}, signature={signature}'


@router.post("/send")
async def send_sms(body: SmsSendRequest):
    api_key    = settings.solapi_api_key
    api_secret = settings.solapi_api_secret

    if not api_key or not api_secret:
        return {"success_count": 0, "fail_count": len(body.phones), "error": "Solapi 인증 정보가 설정되지 않았습니다."}

    if not body.sender:
        return {"success_count": 0, "fail_count": len(body.phones), "error": "발신 번호가 설정되지 않았습니다."}

    messages = [
        {"to": phone, "from": body.sender, "text": body.message}
        for phone in body.phones
    ]

    try:
        resp = requests.post(
            "https://api.solapi.com/messages/v4/send-many",
            json={"messages": messages},
            headers={
                "Content-Type": "application/json",
                "Authorization": _solapi_auth_header(api_key, api_secret),
            },
            timeout=30,
        )
        data = resp.json()

        if resp.status_code == 200:
            success_count = data.get("groupInfo", {}).get("count", {}).get("success", 0)
            fail_count    = data.get("groupInfo", {}).get("count", {}).get("error", 0)
            return {
                "success_count": success_count,
                "fail_count":    fail_count,
                "group_id":      data.get("groupInfo", {}).get("groupId"),
                "raw":           data,
            }
        else:
            return {
                "success_count": 0,
                "fail_count":    len(body.phones),
                "error":         data.get("errorMessage", resp.text),
                "raw":           data,
            }

    except Exception as e:
        return {
            "success_count": 0,
            "fail_count":    len(body.phones),
            "error":         str(e),
        }
