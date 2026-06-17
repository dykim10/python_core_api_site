"""
SNS 수집 서비스 (app/services/sns_service.py)

대회(race_edition_id) 기준으로 YouTube / Instagram 콘텐츠를 수집해
review.youtube_cache / review.instagram_cache 에 upsert 한다.

수집 해시태그: 대회명 + 연도 조합
  예) 서울마라톤 2025년 → ["서울마라톤", "서울마라톤2025"]

[함수]
  fetch_youtube(race_edition_id, max_items, live)
  fetch_instagram(race_edition_id, max_items, live)
  embed_youtube_cache(race_edition_id, live)     — RAG 임베딩
  embed_instagram_cache(race_edition_id, live)   — RAG 임베딩
"""

import logging
from datetime import datetime, timezone

from app.core.database import review_db
from app.services.apify_client import run_actor
from app.services import rag_service

logger = logging.getLogger(__name__)

YOUTUBE_ACTOR   = "streamers/youtube-scraper"
INSTAGRAM_ACTOR = "apify/instagram-scraper"


# ── 대회 정보 조회 ────────────────────────────────────────────────────────────

def _get_edition_info(race_edition_id: int, live: bool) -> dict:
    rows = review_db(live).table("race_editions") \
        .select("id, year, races(name)") \
        .eq("id", race_edition_id) \
        .limit(1) \
        .execute().data
    if not rows:
        raise ValueError(f"race_edition_id={race_edition_id} 없음")
    return rows[0]


def _build_hashtags(race_name: str, year: int | None) -> list[str]:
    tags = [race_name]
    if year:
        tags.append(f"{race_name}{year}")
    return tags


# ── YouTube 수집 ──────────────────────────────────────────────────────────────

def fetch_youtube(race_edition_id: int, max_items: int = 20, live: bool = True) -> int:
    """YouTube 영상을 수집해 review.youtube_cache 에 upsert. 저장 건수 반환."""
    info = _get_edition_info(race_edition_id, live)
    race_name = (info.get("races") or {}).get("name", "")
    year      = info.get("year")
    hashtags  = _build_hashtags(race_name, year)

    all_items: list[dict] = []
    for tag in hashtags:
        try:
            items = run_actor(
                YOUTUBE_ACTOR,
                run_input={"searchKeywords": [tag], "maxResults": max_items},
                timeout_secs=120,
            )
            all_items.extend(items)
        except Exception as e:
            logger.warning(f"[SNS] YouTube 수집 실패 ({tag}): {e}")

    if not all_items:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    seen: set[str] = set()
    records = []
    for item in all_items:
        video_id = str(item.get("id") or item.get("videoId") or "")
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)

        published_raw = item.get("date") or item.get("publishedAt") or None
        published_str = str(published_raw)[:10] if published_raw else None

        records.append({
            "race_edition_id": race_edition_id,
            "video_id":        video_id,
            "title":           (item.get("title") or "")[:500],
            "description":     (item.get("description") or "")[:2000],
            "url":             item.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail_url":   item.get("thumbnailUrl"),
            "view_count":      item.get("viewCount"),
            "published_at":    published_str,
            "fetched_at":      now,
        })

    if records:
        review_db(live).table("youtube_cache").upsert(
            records, on_conflict="video_id"
        ).execute()
        logger.info(f"[SNS] YouTube {len(records)}건 저장 (edition={race_edition_id})")

    return len(records)


# ── Instagram 수집 ────────────────────────────────────────────────────────────

def fetch_instagram(race_edition_id: int, max_items: int = 30, live: bool = True) -> int:
    """Instagram 포스트를 수집해 review.instagram_cache 에 upsert. 저장 건수 반환."""
    info = _get_edition_info(race_edition_id, live)
    race_name = (info.get("races") or {}).get("name", "")
    year      = info.get("year")
    hashtags  = _build_hashtags(race_name, year)

    all_items: list[dict] = []
    for tag in hashtags:
        try:
            items = run_actor(
                INSTAGRAM_ACTOR,
                run_input={"hashtags": [tag], "resultsLimit": max_items},
                timeout_secs=180,
            )
            all_items.extend(items)
        except Exception as e:
            logger.warning(f"[SNS] Instagram 수집 실패 ({tag}): {e}")

    if not all_items:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    seen: set[str] = set()
    records = []
    for item in all_items:
        post_id = str(item.get("id") or item.get("shortCode") or "")
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)

        caption = (item.get("caption") or "")[:2000]

        posted_raw = item.get("timestamp") or item.get("takenAt") or None
        posted_str = str(posted_raw)[:10] if posted_raw else None

        records.append({
            "race_edition_id": race_edition_id,
            "post_id":         post_id,
            "caption":         caption,
            "media_url":       item.get("videoUrl") or item.get("displayUrl"),
            "thumbnail_url":   item.get("displayUrl"),
            "like_count":      item.get("likesCount") or 0,
            "permalink":       item.get("url") or f"https://www.instagram.com/p/{item.get('shortCode','')}/",
            "posted_at":       posted_str,
            "fetched_at":      now,
        })

    if records:
        review_db(live).table("instagram_cache").upsert(
            records, on_conflict="post_id"
        ).execute()
        logger.info(f"[SNS] Instagram {len(records)}건 저장 (edition={race_edition_id})")

    return len(records)


# ── SNS 임베딩 (Phase 9 RAG) ──────────────────────────────────────────────────

def embed_youtube_cache(race_edition_id: int, live: bool = True) -> int:
    """해당 에디션 YouTube 캐시 항목에 임베딩 생성 후 저장. 처리 건수 반환."""
    rows = review_db(live).table("youtube_cache") \
        .select("id, title, description") \
        .eq("race_edition_id", race_edition_id) \
        .is_("embedding", "null") \
        .execute().data

    count = 0
    for row in rows:
        text = f"{row.get('title', '')} {row.get('description', '')}".strip()
        if not text:
            continue
        try:
            embedding = rag_service.generate_embedding(text)
            vector_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
            review_db(live).table("youtube_cache") \
                .update({"embedding": vector_str}) \
                .eq("id", row["id"]).execute()
            count += 1
        except Exception as e:
            logger.warning(f"[SNS] YouTube 임베딩 실패 id={row['id']}: {e}")

    logger.info(f"[SNS] YouTube 임베딩 {count}건 완료 (edition={race_edition_id})")
    return count


def embed_instagram_cache(race_edition_id: int, live: bool = True) -> int:
    """해당 에디션 Instagram 캐시 항목에 임베딩 생성 후 저장. 처리 건수 반환."""
    rows = review_db(live).table("instagram_cache") \
        .select("id, caption") \
        .eq("race_edition_id", race_edition_id) \
        .is_("embedding", "null") \
        .execute().data

    count = 0
    for row in rows:
        text = (row.get("caption") or "").strip()
        if not text:
            continue
        try:
            embedding = rag_service.generate_embedding(text)
            vector_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
            review_db(live).table("instagram_cache") \
                .update({"embedding": vector_str}) \
                .eq("id", row["id"]).execute()
            count += 1
        except Exception as e:
            logger.warning(f"[SNS] Instagram 임베딩 실패 id={row['id']}: {e}")

    logger.info(f"[SNS] Instagram 임베딩 {count}건 완료 (edition={race_edition_id})")
    return count
