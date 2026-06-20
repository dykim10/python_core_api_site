"""Quick WA crawler smoke test (no pytest required)."""
from app.services.race_crawler import (
    crawl_wa_label_races,
    map_wa_label,
    normalize_wa_name_en,
    parse_wa_venue,
)
from app.services.wa_graphql import fetch_minisite_calendar, fetch_organiser_info


def test_mapping():
    assert map_wa_label("GW", "Platinum") == "platinum"
    assert map_wa_label("E", "Label") == "label"
    city, code = parse_wa_venue("Schwäbisch Hall (GER)")
    assert city == "Schwäbisch Hall" and code == "GER"
    assert normalize_wa_name_en("40. OPTIMA X") == "OPTIMA X"
    print("mapping OK")


def test_graphql():
    e2026 = fetch_minisite_calendar(2026)
    e2025 = fetch_minisite_calendar(2025)
    assert len(e2026) > 200
    assert len(e2025) > 200
    assert e2025[0]["id"] != e2026[0]["id"]
    print(f"graphql OK 2026={len(e2026)} 2025={len(e2025)}")

    sample_id = e2026[0]["id"]
    org = fetch_organiser_info(sample_id)
    print(f"organiser sample id={sample_id} has_data={bool(org)}")


def test_crawl():
    races = crawl_wa_label_races(2026, fetch_organiser=False)
    assert len(races) > 200
    r = races[0]
    assert r["wa_label"] in ("platinum", "gold", "elite", "label")
    assert r["source_url"].endswith("/result")
    print(f"crawl OK n={len(races)} sample={r['name_en'][:40]}")


if __name__ == "__main__":
    test_mapping()
    test_graphql()
    test_crawl()
    print("ALL PASS")
