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
