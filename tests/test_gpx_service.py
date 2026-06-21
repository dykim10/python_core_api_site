"""GPX 좌표 파싱 단위 테스트."""
import math

from app.services.gpx_service import (
    _douglas_peucker,
    _latlng_to_xy,
    _marker_distances_m,
    parse_gpx_bytes,
)


def _sample_gpx_bytes(num_points: int = 200, total_km: float = 42.0) -> bytes:
    total_m = total_km * 1000
    points = []
    for i in range(num_points):
        dist = (total_m / (num_points - 1)) * i if num_points > 1 else 0
        lat = 37.5 + (dist / total_m) * 0.05
        lng = 127.0 + (dist / total_m) * 0.08
        ele = 10 + math.sin(i / 10) * 5
        points.append(
            f'<trkpt lat="{lat:.6f}" lon="{lng:.6f}"><ele>{ele:.1f}</ele></trkpt>'
        )
    body = "".join(points)
    return f'<?xml version="1.0"?><gpx version="1.1"><trk><trkseg>{body}</trkseg></trk></gpx>'.encode()


class TestGpxCoordinates:
    def test_parse_returns_coordinates_and_markers(self):
        parsed = parse_gpx_bytes(_sample_gpx_bytes())
        assert parsed is not None
        assert len(parsed["coordinates"]) >= 2
        assert len(parsed["coordinates"]) <= 300
        assert parsed["markers"][0]["km"] == 0
        assert parsed["markers"][0]["label"] == "출발"
        assert parsed["markers"][-1]["label"] == "도착"

    def test_marker_distances_full_marathon(self):
        distances = _marker_distances_m(42_195)
        assert distances[0] == 0.0
        assert 5000.0 in distances
        assert abs(distances[-1] - 42_195) < 1.0

    def test_marker_distances_10k(self):
        distances = _marker_distances_m(10_000)
        assert distances == [0.0, 5000.0, 10_000.0]

    def test_douglas_peucker_reduces_points(self):
        ref_lat, ref_lng = 37.5, 127.0
        raw = []
        for i in range(500):
            lat = 37.5 + i * 0.0001
            lng = 127.0 + i * 0.0001
            x, y = _latlng_to_xy(lat, lng, ref_lat, ref_lng)
            raw.append((lat, lng, x, y))
        simplified = _douglas_peucker(raw, 10.0)
        assert len(simplified) < len(raw)
        assert simplified[0] == raw[0]
        assert simplified[-1] == raw[-1]

    def test_invalid_gpx_returns_none(self):
        assert parse_gpx_bytes(b"not gpx") is None
