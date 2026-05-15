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
        .order("log_date", desc=True)
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
