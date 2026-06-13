"""
이메일 발송 서비스 (app/services/email_service.py)

Resend API를 통해 이메일을 발송한다.
CORE API 내부(스케줄러, 백업 알림 등)에서 직접 호출하거나
POST /api/email/send 엔드포인트를 통해 외부에서 호출할 수 있다.
"""
import resend
from app.core.config import settings


def send_email(
    to: str | list[str],
    subject: str,
    html: str,
    text: str = "",
):
    resend.api_key = settings.resend_api_key
    from_field = f"{settings.mail_from_name} <{settings.mail_from_address}>"
    # from_field = "PAC-RUN <onboarding@resend.dev>" # 테스트용
    to_list = [to] if isinstance(to, str) else to

    params: resend.Emails.SendParams = {
        "from": from_field,
        "to": to_list,
        "subject": subject,
        "html": html,
    }
    if text:
        params["text"] = text

    return resend.Emails.send(params)
