"""
암호화/복호화 라우터 (app/api/routes/crypto.py)

개인정보(이메일·이름) 암호화·복호화를 처리한다.
Laravel(CREW/REVIEW) 의 CryptoService 가 이 엔드포인트를 호출하여
AES 키를 PHP 측에 보관하지 않도록 설계한다.

[엔드포인트]
  POST /api/crypto/encrypt
    요청 : {"value": "평문"}
    응답 : {"encrypted": "Fernet 암호문", "hash": "SHA-256 해시"}
    용도 : 회원가입 시 이메일·이름 암호화 + email_hash 생성

  POST /api/crypto/decrypt
    요청 : {"value": "Fernet 암호문"}
    응답 : {"decrypted": "평문"}
    용도 : 개인정보 조회 시 복호화
    주의 : Laravel 호출 전 반드시 super_admin 권한 검증 필수

[보안 주의]
  이 엔드포인트는 자체 인증이 없으므로
  Nginx 에서 내부 IP(127.0.0.1) 요청만 허용해야 한다.
  외부 공개 절대 금지.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.utils.crypto import encrypt, decrypt, hash_email

router = APIRouter(prefix="/api/crypto", tags=["crypto"])


class EncryptRequest(BaseModel):
    value: str


class EncryptResponse(BaseModel):
    encrypted: str
    hash: str


class DecryptRequest(BaseModel):
    value: str


class DecryptResponse(BaseModel):
    decrypted: str


@router.post("/encrypt", response_model=EncryptResponse)
def encrypt_value(req: EncryptRequest):
    if not req.value.strip():
        raise HTTPException(status_code=422, detail="value가 비어 있습니다.")

    encrypted = encrypt(req.value)
    hashed = hash_email(req.value)

    return EncryptResponse(encrypted=encrypted, hash=hashed)


@router.post("/decrypt", response_model=DecryptResponse)
def decrypt_value(req: DecryptRequest):
    """복호화 — 호출 전 Laravel에서 super_admin 권한 검증 필수"""
    if not req.value.strip():
        raise HTTPException(status_code=422, detail="value가 비어 있습니다.")

    decrypted = decrypt(req.value)

    return DecryptResponse(decrypted=decrypted)
