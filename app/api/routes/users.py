"""
사용자 라우터 (app/api/routes/users.py)

public.users 테이블의 기본 CRUD.
현재는 내부 관리 또는 테스트 용도로 제한적으로 사용하며,
실제 회원가입 / 로그인은 CREW / REVIEW(Laravel Breeze) 에서 처리한다.

[엔드포인트]
  GET  /api/users/{user_id}
    회원 단건 조회 (id, email, name, nickname, role, is_beta, created_at 만 선택)
    없으면 HTTP 404

  POST /api/users/
    회원 생성 (UserCreate 스키마 검증)
    비밀번호를 SHA-256 으로 해시해서 저장

[주의]
  이 라우터의 SHA-256 해시는 Laravel Bcrypt 와 호환되지 않는다.
  실제 로그인 인증은 반드시 Laravel 에서만 처리해야 한다.
"""
from fastapi import APIRouter, HTTPException
from app.core.database import public_db
from app.models.schemas import UserCreate
import hashlib

router = APIRouter(prefix="/api/users", tags=["users"])


def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


@router.get("/{user_id}", response_model=dict)
def get_user(user_id: int):
    res = (
        public_db()
        .table("users")
        .select("id,email,name,nickname,role,is_beta,created_at")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="회원 없음")
    return res.data


@router.post("/", response_model=dict)
def create_user(payload: UserCreate):
    data = {
        "email": payload.email,
        "password": _hash_password(payload.password),
        "name": payload.name,
        "nickname": payload.nickname,
        "invite_code": payload.invite_code,
    }
    try:
        res = public_db().table("users").insert(data).execute()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return res.data[0]
