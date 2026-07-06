"""
다니엘스 VDOT 계산 유틸 (순수 함수).

공식:
  v (m/min) = distance_m / time_min
  VO2 수요   = -4.60 + 0.182258·v + 0.000104·v²
  %VO2max   = 0.8 + 0.1894393·e^(−0.012778·t) + 0.2989558·e^(−0.1932605·t)
  VDOT      = VO2 수요 / %VO2max
"""
import math
from typing import Any

DISTANCE_M = {
    "1K": 1000,
    "5K": 5000,
    "10K": 10000,
    "HALF": 21097.5,
    "FULL": 42195,
}


def calc_vdot(distance_m: float, time_sec: float) -> float:
    """거리(m)와 기록(초)으로 VDOT 계산. 소수 1자리 반환."""
    if distance_m <= 0 or time_sec <= 0:
        raise ValueError("거리와 시간은 0보다 커야 합니다.")
    time_min = time_sec / 60.0
    v = distance_m / time_min
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v * v
    pct_vo2max = (
        0.8
        + 0.1894393 * math.exp(-0.012778 * time_min)
        + 0.2989558 * math.exp(-0.1932605 * time_min)
    )
    if pct_vo2max <= 0:
        raise ValueError("VO2max 비율 계산 오류")
    return round(vo2 / pct_vo2max, 1)


def _pace_for_vdot_at_distance(vdot: float, distance_m: float) -> float:
    """주어진 VDOT에서 특정 거리 완주 시간(초)을 이분탐색으로 역산."""
    lo, hi = 60.0, 36000.0  # 1분 ~ 10시간
    for _ in range(60):
        mid = (lo + hi) / 2
        try:
            v = calc_vdot(distance_m, mid)
        except ValueError:
            hi = mid
            continue
        if v > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def training_paces(vdot: float) -> dict[str, int]:
    """
    VDOT 기반 E/M/T/I 페이스 (초/km) 반환.
    E: easy (마라톤 페이스 +65%), M: marathon, T: threshold, I: interval
    """
    marathon_sec = _pace_for_vdot_at_distance(vdot, DISTANCE_M["FULL"])
    marathon_pace = marathon_sec / (DISTANCE_M["FULL"] / 1000)

    def sec_per_km(total_sec: float, dist_m: float) -> int:
        return int(round(total_sec / (dist_m / 1000)))

    m_pace = sec_per_km(marathon_sec, DISTANCE_M["FULL"])
    e_pace = int(round(m_pace * 1.25))
    t_sec = _pace_for_vdot_at_distance(vdot, DISTANCE_M["10K"])
    t_pace = sec_per_km(t_sec, DISTANCE_M["10K"])
    i_sec = _pace_for_vdot_at_distance(vdot, DISTANCE_M["5K"])
    i_pace = sec_per_km(i_sec, DISTANCE_M["5K"])

    return {"E": e_pace, "M": m_pace, "T": t_pace, "I": i_pace}


def compare_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    거리별 PB 리스트 → VDOT 배열 + 유형 진단.

    records: [{"distance_type": "5K", "record_seconds": 1350}, ...]
    """
    vdots: dict[str, float] = {}
    for rec in records:
        dist_type = rec.get("distance_type") or rec.get("distance")
        seconds = rec.get("record_seconds") or rec.get("time_seconds")
        if not dist_type or not seconds:
            continue
        dist_m = DISTANCE_M.get(str(dist_type).upper())
        if not dist_m:
            continue
        try:
            vdots[str(dist_type).upper()] = calc_vdot(dist_m, float(seconds))
        except (ValueError, TypeError):
            continue

    diagnosis = "insufficient_data"
    v5 = vdots.get("5K")
    v10 = vdots.get("10K")
    vfull = vdots.get("FULL")

    mid_avg = None
    if v5 is not None and v10 is not None:
        mid_avg = (v5 + v10) / 2
    elif v5 is not None:
        mid_avg = v5
    elif v10 is not None:
        mid_avg = v10

    if mid_avg is not None and vfull is not None:
        gap = mid_avg - vfull
        if gap >= 3:
            diagnosis = "endurance_deficit"
        elif gap < 2:
            diagnosis = "balanced"

    return {
        "vdots": vdots,
        "diagnosis": diagnosis,
        "paces": training_paces(list(vdots.values())[0]) if vdots else {},
    }
