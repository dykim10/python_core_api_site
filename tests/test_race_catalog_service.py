from app.services.race_catalog_service import list_active_races


def test_list_active_races_callable():
    assert callable(list_active_races)


def test_list_active_races_enriches_keys(monkeypatch):
    """최신 edition 키가 붙는지 — DB 없이 mock."""

    class FakeQuery:
        def __init__(self, data):
            self._data = data

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def in_(self, *a, **k):
            return self

        def order(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            return type("R", (), {"data": self._data})()

    races_data = [{"id": 1, "name": "테스트마라톤", "is_active": True}]
    editions_data = [
        {"race_id": 1, "year": 2024, "race_date": "2024-03-01"},
        {"race_id": 1, "year": 2025, "race_date": "2025-03-16"},
    ]
    calls = {"n": 0}

    def fake_table(name):
        calls["n"] += 1
        if name == "races":
            return FakeQuery(races_data)
        return FakeQuery(editions_data)

    class FakeDb:
        def table(self, name):
            return fake_table(name)

    monkeypatch.setattr(
        "app.services.race_catalog_service.review_db",
        lambda: FakeDb(),
        raising=False,
    )
    # review_db is imported inside function — patch app.core.database.review_db
    monkeypatch.setattr("app.core.database.review_db", lambda: FakeDb())

    rows = list_active_races(limit=10)
    assert len(rows) == 1
    assert rows[0]["latest_edition_year"] == 2025
    assert rows[0]["latest_race_date"] == "2025-03-16"
