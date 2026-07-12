"""
@pac-run Instagram 피드 수집 (crew.instagram_cache)

Apify instagram-scraper → crew 스키마 upsert.
REVIEW 해시태그 수집(sns_service)과 별개.
"""
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import crew_db
from app.services.apify_client import run_actor

logger = logging.getLogger(__name__)

INSTAGRAM_ACTOR = "apify/instagram-scraper"
DEFAULT_USERNAME = "pac_run"


def _map_media_type(raw: str | None) -> str:
    mapping = {"Image": "IMAGE", "Video": "VIDEO", "Sidecar": "CAROUSEL_ALBUM"}
    return mapping.get(raw or "", "IMAGE")


def _parse_posted_at(raw) -> str | None:
    """Apify timestamp / ISO / Unix(seconds|ms) → UTC ISO8601."""
    if raw is None:
        return None

    if isinstance(raw, (int, float)):
        ts = int(raw)
        if ts > 1_000_000_000_000:
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    text = str(raw).strip()
    if not text:
        return None

    if text.isdigit():
        ts = int(text)
        if ts > 1_000_000_000_000:
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    if "T" in text:
        return text.replace("Z", "+00:00") if text.endswith("Z") else text

    return text[:19]


def _posted_at_sort_key(item: dict) -> float:
    raw = (
        item.get("timestamp")
        or item.get("takenAt")
        or item.get("taken_at")
        or item.get("takenAtTimestamp")
    )
    parsed = _parse_posted_at(raw)
    if not parsed:
        return 0.0
    try:
        return datetime.fromisoformat(parsed.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def fetch_crew_instagram(
    username: str | None = None,
    max_items: int = 12,
    live: bool = False,
) -> int:
    """Apify로 계정 피드 수집 → crew.instagram_cache upsert. 저장 건수 반환."""
    if not settings.apify_api_key:
        logger.warning("[Instagram] APIFY_API_KEY 미설정 — 수집 건너뜀")
        return 0

    handle = (username or getattr(settings, "instagram_username", None) or DEFAULT_USERNAME).lstrip("@")
    profile_url = f"https://www.instagram.com/{handle}/"

    try:
        items = run_actor(
            INSTAGRAM_ACTOR,
            run_input={
                "resultsType": "posts",
                "directUrls": [profile_url],
                "resultsLimit": max_items,
                "addParentData": False,
            },
            timeout_secs=180,
        )
    except Exception as e:
        logger.error(f"[Instagram] Apify 수집 실패 (@{handle}): {e}")
        raise

    if not items:
        logger.warning(f"[Instagram] Apify 결과 0건 (@{handle}, url={profile_url})")

    # Apify는 프로필 피드를 오래된 순으로 반환하는 경우가 많음 → 최신 우선 정렬
    items = sorted(items, key=_posted_at_sort_key, reverse=True)

    now = datetime.now(timezone.utc).isoformat()
    records = []
    seen: set[str] = set()

    for item in items:
        post_id = str(
            item.get("id")
            or item.get("shortCode")
            or item.get("code")
            or ""
        )
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)

        media_url = (
            item.get("videoUrl")
            or item.get("displayUrl")
            or (item.get("images") or [None])[0]
            or ""
        )
        posted_raw = (
            item.get("timestamp")
            or item.get("takenAt")
            or item.get("taken_at")
            or item.get("takenAtTimestamp")
        )
        posted_at = _parse_posted_at(posted_raw)
        short_code = item.get("shortCode") or item.get("code") or post_id

        records.append({
            "post_id": post_id,
            "media_type": _map_media_type(item.get("type")),
            "media_url": media_url,
            "thumbnail_url": item.get("displayUrl") or media_url,
            "caption": (item.get("caption") or "")[:2000],
            "like_count": item.get("likesCount") or item.get("likes") or 0,
            "comments_count": item.get("commentsCount") or item.get("comments") or 0,
            "permalink": item.get("url") or f"https://www.instagram.com/p/{short_code}/",
            "posted_at": posted_at,
            "fetched_at": now,
        })

    if records:
        crew_db(live).table("instagram_cache").upsert(
            records,
            on_conflict="post_id",
        ).execute()
        logger.info(f"[Instagram] {len(records)}건 저장 (@{handle})")

    from app.services.system_log_service import db_log
    db_log("crawler", "info", f"Instagram 수집 완료 (@{handle})", {
        "saved": len(records),
        "max_items": max_items,
    })

    return len(records)


def list_crew_instagram(limit: int = 12, live: bool = False) -> list[dict]:
    """crew.instagram_cache 최신 목록."""
    rows = (
        crew_db(live)
        .table("instagram_cache")
        .select("*")
        .order("posted_at", desc=True)
        .order("post_id", desc=True)
        .limit(limit)
        .execute()
        .data
    )
    return rows or []
