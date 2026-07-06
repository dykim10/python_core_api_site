"""VDOT 계산 단위 테스트."""
from app.services.vdot import calc_vdot, compare_records, training_paces


class TestVdot:
    def test_5k_22_30(self):
        """5K 22:30 → VDOT ≈ 44"""
        vdot = calc_vdot(5000, 22 * 60 + 30)
        assert abs(vdot - 44.0) < 1.0

    def test_training_paces_returns_four_zones(self):
        paces = training_paces(44.0)
        assert set(paces.keys()) == {"E", "M", "T", "I"}
        assert paces["E"] > paces["M"] > paces["T"]

    def test_compare_records_endurance_deficit(self):
        result = compare_records([
            {"distance_type": "5K", "record_seconds": 22 * 60 + 30},
            {"distance_type": "10K", "record_seconds": 47 * 60},
            {"distance_type": "FULL", "record_seconds": 4 * 3600 + 30 * 60},
        ])
        assert result["diagnosis"] in ("endurance_deficit", "balanced", "insufficient_data")
        assert "5K" in result["vdots"]

    def test_compare_records_insufficient_data(self):
        result = compare_records([{"distance_type": "5K", "record_seconds": 1350}])
        assert result["diagnosis"] == "insufficient_data"
