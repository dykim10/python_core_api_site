import hashlib
from functools import lru_cache
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from app.core.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.encrypt_key
    if not key:
        raise RuntimeError("ENCRYPT_KEY 환경변수가 설정되지 않았습니다.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def hash_email(email: str) -> str:
    """로그인/중복 검색용 SHA-256 단방향 해시"""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def encrypt(value: str | None) -> str | None:
    """개인정보 Fernet AES-128 양방향 암호화"""
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    """개인정보 Fernet AES-128 복호화 — InvalidToken 시 HTTP 500"""
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        raise HTTPException(status_code=500, detail="복호화 실패: 키 불일치 또는 손상된 데이터")
