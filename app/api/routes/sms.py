"""
SMS 발송 API (app/api/routes/sms.py)

Solapi REST API를 통해 단체 문자를 발송한다.
"""
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.services.scheduled_sms_service import process_scheduled_sms
from app.services.solapi_service import (
    delete_sender,
    list_sender_numbers,
    register_sender,
    send_many,
    solapi_auth_header,
    verify_sender,
)
import requests

router = APIRouter(prefix="/api/sms", tags=["sms"])


class SmsSendRequest(BaseModel):
    phones: list[str]
    message: str
    sender: str


class SenderRegisterRequest(BaseModel):
    phone_number: str


class SenderVerifyRequest(BaseModel):
    phone_number: str
    certification_code: str


def _check_backup_api_key(x_backup_api_key: str | None) -> None:
    if not settings.backup_api_key:
        raise HTTPException(status_code=503, detail="BACKUP_API_KEY 미설정")
    if x_backup_api_key != settings.backup_api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/send")
async def send_sms(body: SmsSendRequest):
    return send_many(body.phones, body.message, body.sender)


@router.post("/scheduled/process")
async def trigger_scheduled_sms(
    x_backup_api_key: str | None = Header(default=None),
):
    """예약 문자 스케줄러 수동 트리거 (로컬 테스트용)."""
    _check_backup_api_key(x_backup_api_key)
    process_scheduled_sms()
    return {"ok": True}


@router.get("/senders")
async def get_senders(all: int = Query(default=0)):
    """솔라피에 등록된 발신번호 목록 조회. all=1 이면 전체 상태 반환."""
    return list_sender_numbers(include_all_statuses=all == 1)


@router.post("/senders/register")
async def register_sms_sender(body: SenderRegisterRequest):
    return register_sender(body.phone_number)


@router.post("/senders/verify")
async def verify_sms_sender(body: SenderVerifyRequest):
    return verify_sender(body.phone_number, body.certification_code)


@router.delete("/senders/{phone_number}")
async def delete_sms_sender(phone_number: str):
    return delete_sender(phone_number)


@router.get("/messages/{group_id}")
async def get_sms_messages(group_id: str, limit: int = 100):
    """발송 그룹의 개별 메시지 목록 조회"""
    api_key = settings.solapi_api_key
    api_secret = settings.solapi_api_secret

    if not api_key or not api_secret:
        return {"error": "Solapi 인증 정보가 설정되지 않았습니다."}

    try:
        resp = requests.get(
            f"https://api.solapi.com/messages/v4/groups/{group_id}/messages",
            params={"limit": limit},
            headers={"Authorization": solapi_auth_header(api_key, api_secret)},
            timeout=15,
        )
        data = resp.json()

        if resp.status_code != 200:
            return {"error": data.get("errorMessage", resp.text)}

        message_dict = data.get("messageList", {})
        messages = list(message_dict.values())
        return {
            "group_id": group_id,
            "total": len(messages),
            "messages": [
                {
                    "message_id": m.get("messageId"),
                    "from": m.get("from"),
                    "to": m.get("to"),
                    "text": m.get("text"),
                    "status_code": m.get("statusCode"),
                    "status": m.get("status"),
                    "type": m.get("type"),
                    "date_created": m.get("dateCreated"),
                    "date_received": m.get("dateReceived"),
                }
                for m in messages
            ],
        }

    except Exception as e:
        return {"error": str(e)}


@router.get("/status/{group_id}")
async def get_sms_status(group_id: str):
    """발송 그룹의 현재 수신 결과 집계 조회"""
    api_key = settings.solapi_api_key
    api_secret = settings.solapi_api_secret

    if not api_key or not api_secret:
        return {"error": "Solapi 인증 정보가 설정되지 않았습니다."}

    try:
        resp = requests.get(
            f"https://api.solapi.com/messages/v4/groups/{group_id}",
            headers={"Authorization": solapi_auth_header(api_key, api_secret)},
            timeout=10,
        )
        data = resp.json()

        if resp.status_code == 200:
            count = data.get("count", {})
            return {
                "group_id": group_id,
                "total": count.get("total", 0),
                "success": count.get("sentSuccess", 0),
                "error": count.get("sentFailed", 0),
                "waiting": count.get("sentPending", 0),
            }
        return {"error": data.get("errorMessage", resp.text)}

    except Exception as e:
        return {"error": str(e)}
