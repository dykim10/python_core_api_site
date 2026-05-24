"""
Pydantic 스키마 정의 (app/models/schemas.py)

FastAPI 의 요청/응답 데이터 검증에 사용하는 Pydantic 모델 모음.
라우터에서 response_model 파라미터 또는 함수 인수 타입 힌트로 사용한다.

  from app.models.schemas import RunningLogCreate

[모델 목록]
  RunningLogCreate    : 러닝 기록 생성 요청 (user_id, log_date, distance_km 등)
  RunningLogResponse  : RunningLogCreate 를 상속하고 id, created_at 추가 (DB 저장 후 응답)
  UserCreate          : 회원 생성 요청 (email, password, name, nickname, invite_code)
  UserResponse        : 회원 조회 응답 (password 등 민감 정보 제외)

[Pydantic 기본 동작]
  - 선언된 타입과 다른 값이 들어오면 자동으로 형 변환 시도 (coercion)
  - Optional[X] 는 None 허용, 기본값 None
  - EmailStr 은 이메일 형식 자동 검증 (pydantic[email] 패키지 필요)
"""
from pydantic import BaseModel, EmailStr
from datetime import date, datetime
from typing import Optional
from decimal import Decimal


class RunningLogCreate(BaseModel):
    user_id: int
    log_date: date
    distance_km: Optional[Decimal] = None
    avg_pace: Optional[str] = None
    best_pace: Optional[str] = None
    duration_sec: Optional[int] = None
    calories: Optional[int] = None
    avg_heart_rate: Optional[int] = None
    is_indoor: bool = False
    altitude_m: Optional[Decimal] = None
    image_url: Optional[str] = None


class RunningLogResponse(RunningLogCreate):
    id: int
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None
    nickname: Optional[str] = None
    invite_code: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    email: str
    name: Optional[str]
    nickname: Optional[str]
    role: str
    is_beta: bool
    created_at: datetime
