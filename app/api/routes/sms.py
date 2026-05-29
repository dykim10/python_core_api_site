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
            count = data.get("count", {})
            return {
                "success_count": count.get("sentSuccess", 0),
                "fail_count":    count.get("sentFailed", 0),
                "group_id":      data.get("groupId"),
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


@router.get("/senders")
async def get_senders():
    """솔라피에 등록된 발신번호 목록 조회"""
    api_key    = settings.solapi_api_key
    api_secret = settings.solapi_api_secret

    if not api_key or not api_secret:
        return {"senders": [], "error": "Solapi 인증 정보가 설정되지 않았습니다."}

    try:
        resp = requests.get(
            "https://api.solapi.com/senderid/v1/numbers",
            headers={"Authorization": _solapi_auth_header(api_key, api_secret)},
            timeout=10,
        )
        data = resp.json()

        if resp.status_code == 200:
            senders = [
                item["phoneNumber"]
                for item in data.get("senderIds", [])
                if item.get("phoneNumber") and item.get("status") == "ACTIVE"
            ]
            return {"senders": senders}
        else:
            return {"senders": [], "error": data.get("errorMessage", resp.text)}

    except Exception as e:
        return {"senders": [], "error": str(e)}


@router.get("/status/{group_id}")
async def get_sms_status(group_id: str):
    """발송 그룹의 현재 수신 결과 집계 조회 (수동 갱신용)"""
    api_key    = settings.solapi_api_key
    api_secret = settings.solapi_api_secret

    if not api_key or not api_secret:
        return {"error": "Solapi 인증 정보가 설정되지 않았습니다."}

    try:
        resp = requests.get(
            f"https://api.solapi.com/messages/v4/groups/{group_id}",
            headers={"Authorization": _solapi_auth_header(api_key, api_secret)},
            timeout=10,
        )
        data = resp.json()

        if resp.status_code == 200:
            count = data.get("count", {})
            return {
                "group_id": group_id,
                "total":    count.get("total", 0),
                "success":  count.get("sentSuccess", 0),
                "error":    count.get("sentFailed", 0),
                "waiting":  count.get("sentPending", 0),
            }
        else:
            return {"error": data.get("errorMessage", resp.text)}

    except Exception as e:
        return {"error": str(e)}
