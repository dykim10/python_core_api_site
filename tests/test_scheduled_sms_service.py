from app.services.scheduled_sms_service import _normalize_phone


def test_normalize_phone_strips_non_digits():
    assert _normalize_phone("010-1234-5678") == "01012345678"


def test_normalize_phone_rejects_short():
    assert _normalize_phone("12345") is None
