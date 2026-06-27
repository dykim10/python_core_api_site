"""course_elevation_service 단위 테스트."""
import math

import pytest

from app.services.course_elevation_service import (
    ascent_descent,
    build_elevation_profile,
    cumulative_distances,
    haversine_m,
    parse_gpx_points,
    sample_elevation,
)

SAMPLE_GPX = """<?xml version="1.0"?>
<gpx version="1.1">
  <trk><trkseg>
    <trkpt lat="37.0" lon="127.0"><ele>100</ele></trkpt>
    <trkpt lat="37.001" lon="127.0"><ele>110</ele></trkpt>
    <trkpt lat="37.002" lon="127.0"><ele>105</ele></trkpt>
    <trkpt lat="37.003" lon="127.0"><ele>120</ele></trkpt>
  </trkseg></trk>
</gpx>"""


class TestHaversine:
    def test_same_point_zero(self):
        assert haversine_m(37.0, 127.0, 37.0, 127.0) == 0.0

    def test_positive_distance(self):
        d = haversine_m(37.0, 127.0, 37.001, 127.0)
        assert d > 100


class TestBuildProfile:
    def test_profile_structure(self):
        profile = build_elevation_profile(SAMPLE_GPX, interval_m=50.0)
        assert profile["version"] == 1
        assert profile["sampled_interval_m"] == 50.0
        assert profile["point_count"] == len(profile["points"])
        assert profile["points"][0]["dist_m"] == 0
        assert profile["min_elevation_m"] <= profile["max_elevation_m"]
        assert profile["total_ascent_m"] >= 0
        assert profile["total_descent_m"] >= 0

    def test_insufficient_points_raises(self):
        gpx = """<?xml version="1.0"?><gpx><trk><trkseg>
        <trkpt lat="37" lon="127"><ele>10</ele></trkpt>
        </trkseg></trk></gpx>"""
        with pytest.raises(ValueError, match="부족"):
            build_elevation_profile(gpx)

    def test_no_elevation_raises(self):
        gpx = """<?xml version="1.0"?><gpx><trk><trkseg>
        <trkpt lat="37" lon="127"></trkpt>
        <trkpt lat="37.001" lon="127"></trkpt>
        </trkseg></trk></gpx>"""
        with pytest.raises(ValueError):
            build_elevation_profile(gpx)


class TestSampleElevation:
    def test_end_point_included(self):
        points = parse_gpx_points(SAMPLE_GPX)
        cum = cumulative_distances(points)
        sampled = sample_elevation(points, cum, interval_m=1000.0)
        assert math.isclose(sampled[-1][0], cum[-1], rel_tol=0, abs_tol=0.2)

    def test_ascent_descent(self):
        sampled = [(0, 100), (100, 110), (200, 105)]
        up, down = ascent_descent(sampled)
        assert up == 10.0
        assert down == 5.0
