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
