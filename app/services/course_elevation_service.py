"""공식 코스 GPX → 거리×고도 프로파일 (100m 샘플링 + 선형보간)."""
from __future__ import annotations

import math
from typing import Any

import gpxpy

EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def parse_gpx_points(gpx_text: str) -> list[tuple[float, float, float]]:
    gpx = gpxpy.parse(gpx_text)
    pts: list[tuple[float, float, float]] = []
    for track in gpx.tracks:
        for seg in track.segments:
            for pt in seg.points:
                if pt.elevation is not None:
                    pts.append((pt.latitude, pt.longitude, float(pt.elevation)))
    for route in gpx.routes:
        for pt in route.points:
            if pt.elevation is not None:
                pts.append((pt.latitude, pt.longitude, float(pt.elevation)))
    return pts


def cumulative_distances(points: list[tuple[float, float, float]]) -> list[float]:
    cum = [0.0]
    for i in range(1, len(points)):
        lat1, lon1, _ = points[i - 1]
        lat2, lon2, _ = points[i]
        cum.append(cum[-1] + haversine_m(lat1, lon1, lat2, lon2))
    return cum


def sample_elevation(
    points: list[tuple[float, float, float]],
    cum: list[float],
    interval_m: float = 100.0,
) -> list[tuple[float, float]]:
    total = cum[-1]
    targets: list[float] = []
    t = 0.0
    while t < total:
        targets.append(t)
        t += interval_m
    targets.append(total)

    sampled: list[tuple[float, float]] = []
    j = 0
    for target in targets:
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        d0, d1 = cum[j], cum[j + 1]
        e0, e1 = points[j][2], points[j + 1][2]
        if d1 == d0:
            ele = e0
        else:
            ratio = (target - d0) / (d1 - d0)
            ele = e0 + (e1 - e0) * ratio
        sampled.append((round(target, 1), round(ele, 1)))
    return sampled


def ascent_descent(sampled: list[tuple[float, float]]) -> tuple[float, float]:
    up = down = 0.0
    for i in range(1, len(sampled)):
        diff = sampled[i][1] - sampled[i - 1][1]
        if diff > 0:
            up += diff
        else:
            down += -diff
    return round(up, 1), round(down, 1)


def build_elevation_profile(gpx_text: str, interval_m: float = 100.0) -> dict[str, Any]:
    points = parse_gpx_points(gpx_text)
    if len(points) < 2:
        raise ValueError("유효한 GPX 트랙 포인트가 부족합니다.")

    cum = cumulative_distances(points)
    sampled = sample_elevation(points, cum, interval_m)
    up, down = ascent_descent(sampled)
    eles = [e for _, e in sampled]

    return {
        "version": 1,
        "sampled_interval_m": interval_m,
        "total_distance_m": round(cum[-1], 1),
        "point_count": len(sampled),
        "min_elevation_m": min(eles),
        "max_elevation_m": max(eles),
        "total_ascent_m": up,
        "total_descent_m": down,
        "points": [{"dist_m": d, "ele_m": e} for d, e in sampled],
    }
