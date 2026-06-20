"""
GPX 파일 파싱 — 고도/구간 데이터 추출.

업로드 시점에 딱 한 번만 파싱해서 race_courses.elevation_data/segments에
영구 저장한다. 레이스 플랜 생성(race_plan_service.py)은 이 컬럼만 읽으므로,
사용자가 몇 명이든 GPX 다운로드·파싱은 "코스당 1회"로 고정된다.
"""
from __future__ import annotations

import io
import logging
from typing import Any

import gpxpy

logger = logging.getLogger(__name__)

SEGMENT_LENGTH_M = 5000  # 5km 단위 구간 분할
FLAT_GRADE_PCT = 0.8     # 이 값 이상/이하 평균 경사(%)면 오르막/내리막으로 분류


def parse_gpx_bytes(gpx_bytes: bytes) -> dict[str, Any] | None:
    """GPX 바이트 → {elevation_data, segments}. 파싱 실패/포인트 없으면 None (graceful)."""
    try:
        gpx = gpxpy.parse(io.BytesIO(gpx_bytes))
    except Exception as e:
        logger.warning("GPX 파싱 실패: %s", e)
        return None

    points_data = gpx.get_points_data()
    if not points_data:
        logger.warning("GPX에 트랙 포인트가 없음")
        return None

    total_m = points_data[-1].distance_from_start
    uphill, downhill = gpx.get_uphill_downhill()
    elev_min, elev_max = gpx.get_elevation_extremes()

    elevation_data = {
        "total_gain_m": round(uphill, 1) if uphill else 0.0,
        "total_loss_m": round(downhill, 1) if downhill else 0.0,
        "max_m": round(elev_max, 1) if elev_max is not None else None,
        "min_m": round(elev_min, 1) if elev_min is not None else None,
        "distance_km": round(total_m / 1000, 2) if total_m else None,
    }

    return {
        "elevation_data": elevation_data,
        "segments": _build_segments(points_data, total_m),
    }


def _build_segments(points_data, total_m: float) -> list[dict[str, Any]]:
    if not total_m or total_m <= 0:
        return []

    n_segments = max(1, round(total_m / SEGMENT_LENGTH_M))
    seg_len = total_m / n_segments

    segments: list[dict[str, Any]] = []
    for i in range(n_segments):
        start_m = i * seg_len
        end_m = total_m if i == n_segments - 1 else (i + 1) * seg_len

        elevations = [
            pd.point.elevation
            for pd in points_data
            if start_m <= pd.distance_from_start <= end_m and pd.point.elevation is not None
        ]

        gain = 0.0
        characteristic = "평탄"
        if len(elevations) >= 2:
            gain = elevations[-1] - elevations[0]
            seg_m = end_m - start_m
            grade_pct = (gain / seg_m) * 100 if seg_m > 0 else 0
            if grade_pct >= FLAT_GRADE_PCT:
                characteristic = "오르막"
            elif grade_pct <= -FLAT_GRADE_PCT:
                characteristic = "내리막"

        segments.append({
            "km_range": f"{round(start_m / 1000)}-{round(end_m / 1000)}",
            "characteristic": characteristic,
            "gain_m": round(gain, 1),
        })

    return segments
