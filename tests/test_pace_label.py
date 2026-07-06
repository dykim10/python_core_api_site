from app.services.coach_service import _normalize_pace_text, _pace_label


class TestPaceLabel:
    def test_pace_label_minutes_seconds(self):
        assert _pace_label(340) == "5'40\"/km"
        assert _pace_label(280) == "4'40\"/km"
        assert _pace_label(330) == "5'30\"/km"

    def test_normalize_pace_text_in_comment(self):
        raw = "목표 페이스 340초/km의 포인트 훈련이 예정되어 있었으나"
        assert "5'40\"/km" in _normalize_pace_text(raw)
        assert "340초/km" not in _normalize_pace_text(raw)
