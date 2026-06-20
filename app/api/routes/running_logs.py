"""
러닝 기록 라우터 (app/api/routes/running_logs.py)

crew.running_logs 테이블의 기본 CRUD.
현재는 내부 관리 또는 테스트 용도로만 사용하며,
실제 러닝 기록 저장은 CREW(Laravel) 에서 Eloquent 로 직접 처리한다.

[엔드포인트]
  GET    /api/running-logs/user/{user_id}
    특정 사용자의 기록 목록 (log_date 내림차순, limit 기본 20)

  POST   /api/running-logs/
    기록 생성 (RunningLogCreate 스키마 검증)
    Decimal 타입(distance_km, altitude_m)은 float 으로 변환 후 INSERT

  DELETE /api/running-logs/{log_id}
    기록 삭제, {"deleted": log_id} 반환
"""
from fastapi import APIRouter, HTTPException
from app.core.database import crew_db
from app.models.schemas import RunningLogCreate
from typing import List

router = APIRouter(prefix="/api/running-logs", tags=["running-logs"])


@router.get("/user/{user_id}", response_model=List[dict])
def get_user_logs(user_id: int, limit: int = 20):
    res = (
        crew_db()
        .table("running_logs")
        .select("*")
        .eq("user_id", user_id)
        .order("run_date", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


@router.post("/", response_model=dict)
def create_log(payload: RunningLogCreate):
    data = payload.model_dump()
    data["log_date"] = str(data["log_date"])
    if data.get("distance_km") is not None:
        data["distance_km"] = float(data["distance_km"])
    if data.get("altitude_m") is not None:
        data["altitude_m"] = float(data["altitude_m"])

    res = crew_db().table("running_logs").insert(data).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="저장 실패")
    return res.data[0]


@router.delete("/{log_id}")
def delete_log(log_id: int):
    crew_db().table("running_logs").delete().eq("id", log_id).execute()
    return {"deleted": log_id}
