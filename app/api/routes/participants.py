"""
이벤트 참가자 일괄 등록 라우터 (app/api/routes/participants.py)

엑셀 파일을 업로드해 이벤트 참가자를 crew.event_participants 테이블에 일괄 저장한다.
이름 · 이메일 · 휴대폰은 Fernet AES-128 로 암호화해서 저장한다.

POST /api/participants/import
  요청 : multipart/form-data
    file     : xlsx 또는 xls 파일
    event_id : 대상 이벤트 ID (Form 파라미터)
  응답 : {"imported": N, "failed": N, "errors": ["2행: 이름 누락", ...]}

[엑셀 컬럼 매핑 (COLUMN_MAP)]
  이름   → name_enc  (암호화 저장)
  이메일 → email_enc (암호화 저장)
  휴대폰 → phone_enc (암호화 저장)
  메모   → memo      (평문 저장)

[처리 흐름]
  1. 파일 타입 검증 (xlsx / xls 만 허용)
  2. pandas.read_excel 로 파싱
  3. 컬럼명 한글 → 영문 rename (COLUMN_MAP)
  4. 행별로 암호화 후 INSERT
  5. 이름 누락 행은 건너뜀 + errors 에 기록
  6. 결과 집계 반환 (imported / failed / errors)
"""
import io
import pandas as pd
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from app.core.database import crew_db
from app.utils.crypto import encrypt, hash_email

router = APIRouter(prefix="/api/participants", tags=["participants"])

# 엑셀 컬럼명 → DB 컬럼 매핑
COLUMN_MAP = {
    "이름":   "name",
    "이메일": "email",
    "휴대폰": "phone",
    "메모":   "memo",
}


class ImportResponse(BaseModel):
    imported: int
    failed: int
    errors: list[str] = []


@router.post("/import", response_model=ImportResponse)
async def import_participants(
    file: UploadFile = File(...),
    event_id: int = Form(...),
):
    if file.content_type not in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ):
        raise HTTPException(status_code=400, detail="xlsx 또는 xls 파일만 업로드 가능합니다.")

    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"엑셀 파싱 실패: {str(e)}")

    df.rename(columns=COLUMN_MAP, inplace=True)

    imported = 0
    failed = 0
    errors: list[str] = []
    db = crew_db()

    for idx, row in df.iterrows():
        row_num = idx + 2  # 헤더 제외, 1-based

        name_raw  = str(row.get("name",  "") or "").strip()
        email_raw = str(row.get("email", "") or "").strip()
        phone_raw = str(row.get("phone", "") or "").strip()
        memo      = str(row.get("memo",  "") or "").strip() or None

        if not name_raw:
            errors.append(f"{row_num}행: 이름 누락")
            failed += 1
            continue

        try:
            record = {
                "event_id":  event_id,
                "name_enc":  encrypt(name_raw)  if name_raw  else None,
                "email_enc": encrypt(email_raw) if email_raw else None,
                "phone_enc": encrypt(phone_raw) if phone_raw else None,
                "memo":      memo,
            }
            db.table("event_participants").insert(record).execute()
            imported += 1
        except Exception as e:
            errors.append(f"{row_num}행 저장 실패: {str(e)}")
            failed += 1

    return ImportResponse(imported=imported, failed=failed, errors=errors)
