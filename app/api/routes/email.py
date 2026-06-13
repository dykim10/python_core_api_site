"""
이메일 발송 라우터 (app/api/routes/email.py)

POST /api/email/send
  요청: { to, subject, html, text? }
  응답: { success, id }
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.services.email_service import send_email

router = APIRouter(prefix="/api/email", tags=["email"])


class EmailRequest(BaseModel):
    to: str | list[str]
    subject: str
    html: str
    text: Optional[str] = None


@router.post("/send")
def send(req: EmailRequest):
    try:
        result = send_email(req.to, req.subject, req.html, req.text or "")
        return {"success": True, "id": result.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"이메일 발송 실패: {str(e)}")
