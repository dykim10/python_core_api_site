"""
GPX 파일 파싱 — 고도/구간/좌표 데이터 추출.

업로드 시점에 딱 한 번만 파싱해서 race_courses 컬럼에 영구 저장한다.
레이스 플랜 생성(race_plan_service.py)은 DB 컬럼만 읽으므로,
사용자가 몇 명이든 GPX 다운로드·파싱은 "코스당 1회"로 고정된다.
"""
from __future__ import annotations

import io
import logging
import math
from typing import Any

import gpxpy

logger = logging.getLogger(__name__)

SEGMENT_LENGTH_M = 5000  # 5km 단위 구간 분할
FLAT_GRADE_PCT = 0.8     # 이 값 이상/이하 평균 경사(%)면 오르막/내리막으로 분류
DP_EPSILON_M = 10.0      # Douglas-Peucker 허용 오차 (미터)


def parse_gpx_bytes(gpx_bytes: bytes) -> dict[str, Any] | None:
    """GPX 바이트 → {elevation_data, segments, coordinates, markers}. 실패 시 None."""
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

    coordinates = _build_coordinates(points_data)
    markers = _build_markers(points_data, total_m)

    return {
        "elevation_data": elevation_data,
        "segments": _build_segments(points_data, total_m),
        "coordinates": coordinates,
        "markers": markers,
    }


def _latlng_to_xy(lat: float, lng: float, ref_lat: float, ref_lng: float) -> tuple[float, float]:
    x = (lng - ref_lng) * 111_320 * math.cos(math.radians(ref_lat))
    y = (lat - ref_lat) * 110_540
    return x, y


def _perpendicular_distance_m(
    point: tuple[float, float],
    line_start: tuple[float, float],
    line_end: tuple[float, float],
) -> float:
    px, py = point
    x1, y1 = line_start
    x2, y2 = line_end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _douglas_peucker(
    points: list[tuple[float, float, float, float]],
    epsilon_m: float,
) -> list[tuple[float, float, float, float]]:
    """(lat, lng, x, y) 리스트를 epsilon_m 기준으로 단순화."""
    if len(points) <= 2:
        return points

    start = points[0]
    end = points[-1]
    max_dist = 0.0
    max_idx = 0
    for i in range(1, len(points) - 1):
        dist = _perpendicular_distance_m(
            (points[i][2], points[i][3]),
            (start[2], start[3]),
            (end[2], end[3]),
        )
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    if max_dist > epsilon_m:
        left = _douglas_peucker(points[: max_idx + 1], epsilon_m)
        right = _douglas_peucker(points[max_idx:], epsilon_m)
        return left[:-1] + right

    return [start, end]


def _build_coordinates(points_data) -> list[dict[str, float]]:
    raw: list[tuple[float, float, float, float]] = []
    ref_lat = points_data[0].point.latitude
    ref_lng = points_data[0].point.longitude

    for pd in points_data:
        lat = pd.point.latitude
        lng = pd.point.longitude
        x, y = _latlng_to_xy(lat, lng, ref_lat, ref_lng)
        raw.append((lat, lng, x, y))

    simplified = _douglas_peucker(raw, DP_EPSILON_M)
    return [{"lat": round(lat, 6), "lng": round(lng, 6)} for lat, lng, _, _ in simplified]


def _interpolate_latlng(points_data, target_m: float) -> tuple[float, float]:
    if target_m <= 0:
        first = points_data[0].point
        return first.latitude, first.longitude

    for i, pd in enumerate(points_data):
        if pd.distance_from_start >= target_m:
            if i == 0:
                p = pd.point
                return p.latitude, p.longitude
            prev = points_data[i - 1]
            seg = pd.distance_from_start - prev.distance_from_start
            if seg <= 0:
                p = pd.point
                return p.latitude, p.longitude
            t = (target_m - prev.distance_from_start) / seg
            lat = prev.point.latitude + t * (pd.point.latitude - prev.point.latitude)
            lng = prev.point.longitude + t * (pd.point.longitude - prev.point.longitude)
            return lat, lng

    last = points_data[-1].point
    return last.latitude, last.longitude


def _interpolate_elevation(points_data, target_m: float) -> float | None:
    if target_m <= 0:
        return points_data[0].point.elevation

    for i, pd in enumerate(points_data):
        if pd.distance_from_start >= target_m:
            if pd.point.elevation is None:
                return None
            if i == 0:
                return float(pd.point.elevation)
            prev = points_data[i - 1]
            if prev.point.elevation is None:
                return float(pd.point.elevation)
            seg = pd.distance_from_start - prev.distance_from_start
            if seg <= 0:
                return float(pd.point.elevation)
            t = (target_m - prev.distance_from_start) / seg
            return float(prev.point.elevation + t * (pd.point.elevation - prev.point.elevation))

    last = points_data[-1].point
    return float(last.elevation) if last.elevation is not None else None


def _elevation_gain_loss_between(points_data, start_m: float, end_m: float) -> tuple[float, float]:
    if start_m >= end_m:
        return 0.0, 0.0

    samples: list[tuple[float, float]] = []
    start_elev = _interpolate_elevation(points_data, start_m)
    if start_elev is not None:
        samples.append((start_m, start_elev))

    for pd in points_data:
        d = pd.distance_from_start
        if start_m < d < end_m and pd.point.elevation is not None:
            samples.append((d, float(pd.point.elevation)))

    end_elev = _interpolate_elevation(points_data, end_m)
    if end_elev is not None:
        samples.append((end_m, end_elev))

    if len(samples) < 2:
        return 0.0, 0.0

    samples.sort(key=lambda item: item[0])
    deduped: list[tuple[float, float]] = []
    for dist, elev in samples:
        if deduped and abs(deduped[-1][0] - dist) < 0.01:
            deduped[-1] = (dist, elev)
        else:
            deduped.append((dist, elev))

    gain = 0.0
    loss = 0.0
    for i in range(1, len(deduped)):
        delta = deduped[i][1] - deduped[i - 1][1]
        if delta > 0:
            gain += delta
        elif delta < 0:
            loss += abs(delta)

    return round(gain, 1), round(loss, 1)


def _marker_distances_m(total_m: float) -> list[float]:
    if total_m <= 0:
        return []

    targets = [0.0]
    d = float(SEGMENT_LENGTH_M)
    while d < total_m - 1.0:
        targets.append(d)
        d += float(SEGMENT_LENGTH_M)

    if abs(targets[-1] - total_m) > 1.0:
        targets.append(total_m)

    return targets


def _build_markers(points_data, total_m: float) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    distances = _marker_distances_m(total_m)

    for idx, dist_m in enumerate(distances):
        lat, lng = _interpolate_latlng(points_data, dist_m)
        km = round(dist_m / 1000, 1)
        is_first = idx == 0
        is_last = idx == len(distances) - 1

        if is_first:
            label = "출발"
        elif is_last:
            label = "도착"
        else:
            label = f"{int(round(km))}km"

        prev_dist = distances[idx - 1] if idx > 0 else 0.0
        elev_m = _interpolate_elevation(points_data, dist_m)
        gain_m, loss_m = (
            (0.0, 0.0) if idx == 0 else _elevation_gain_loss_between(points_data, prev_dist, dist_m)
        )

        marker: dict[str, Any] = {
            "km": km,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "label": label,
            "gain_m": gain_m,
            "loss_m": loss_m,
        }
        if elev_m is not None:
            marker["elev_m"] = round(elev_m, 1)

        markers.append(marker)

    return markers


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
