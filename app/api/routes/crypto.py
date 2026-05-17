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
