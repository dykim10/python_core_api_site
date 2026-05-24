"""
개인정보 암호화 유틸 (app/utils/crypto.py)

cryptography 라이브러리의 Fernet 을 사용해 개인정보를 양방향 암호화한다.
Fernet 은 AES-128-CBC + HMAC-SHA256 을 결합한 대칭키 암호화 방식이다.

[_fernet() — 싱글턴]
  lru_cache(maxsize=1) 로 Fernet 인스턴스를 최초 1회만 생성하고 재사용.
  ENCRYPT_KEY 미설정 시 RuntimeError 발생.
  ENCRYPT_KEY 생성 방법:
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())  # 결과를 .env 에 저장

[함수]
  hash_email(email) → str
    이메일을 SHA-256 단방향 해시로 변환 (소문자 + strip 정규화 후 해시)
    로그인 조회 / 중복 가입 확인에 사용 — 역복호화 불가

  encrypt(value) → str | None
    평문 → Fernet 암호문 (URL-safe base64 인코딩 문자열)
    None 입력 시 None 반환

  decrypt(value) → str | None
    Fernet 암호문 → 평문
    키 불일치 또는 데이터 손상 시 InvalidToken 예외 → HTTP 500 응답
    None 입력 시 None 반환
"""
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
