"""World Athletics Label Road Races 크롤러 단위·통합 테스트."""
import pytest

from app.services.race_crawler import (
    crawl_wa_label_races,
    map_wa_label,
    normalize_wa_name_en,
    parse_wa_race_date,
    parse_wa_venue,
)
from app.services.wa_graphql import fetch_minisite_calendar


class TestWaLabelMapping:
    def test_map_platinum_from_subgroup(self):
        assert map_wa_label("GW", "Platinum") == "platinum"

    def test_map_gold(self):
        assert map_wa_label("A", "Gold") == "gold"

    def test_map_elite(self):
        assert map_wa_label("B", "Elite") == "elite"

    def test_map_label_from_subgroup(self):
        assert map_wa_label("E", "Label") == "label"

    def test_map_fallback_ranking_category(self):
        assert map_wa_label("GL", None) == "platinum"
        assert map_wa_label("E", None) == "label"

    def test_parse_venue_with_country(self):
        city, code = parse_wa_venue("Schwäbisch Hall (GER)")
        assert city == "Schwäbisch Hall"
        assert code == "GER"

    def test_parse_venue_plain(self):
        city, code = parse_wa_venue("Tokyo")
        assert city == "Tokyo"
        assert code == ""

    def test_normalize_edition_prefix(self):
        assert normalize_wa_name_en("40. OPTIMA Dreikönigslauf") == "OPTIMA Dreikönigslauf"

    def test_parse_iso_date(self):
        assert parse_wa_race_date("2026-01-06", 2026) == "2026-01-06"

    def test_parse_wikipedia_style_date(self):
        assert parse_wa_race_date("17 Mar", 2024) == "2024-03-17"


@pytest.mark.integration
class TestWaGraphqlLive:
    def test_fetch_minisite_calendar_2026(self):
        events = fetch_minisite_calendar(2026)
        assert len(events) > 200
        assert events[0]["id"]
        assert events[0]["name"]

    def test_fetch_minisite_calendar_2025(self):
        events = fetch_minisite_calendar(2025)
        assert len(events) > 200

    def test_crawl_wa_label_races(self):
        races = crawl_wa_label_races(2026, fetch_organiser=False)
        assert len(races) > 200
        sample = races[0]
        assert sample["wa_competition_id"]
        assert sample["wa_label"] in ("platinum", "gold", "elite", "label")
        assert sample["source"] == "world_athletics"
        assert "/calendar-results/" in sample["source_url"]
