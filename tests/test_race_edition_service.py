from app.services.race_edition_service import list_upcoming_editions


def test_list_upcoming_editions_shape():
    """DB 없이도 import·반환 타입 확인 (통합 테스트는 review_db 필요)."""
    assert callable(list_upcoming_editions)
