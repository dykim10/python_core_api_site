"""
Apify 크롤링 라우터 (app/api/routes/apify.py)

YouTube 영상 검색과 Instagram 포스트 수집을 Apify Actor 로 처리한다.

[엔드포인트]

  GET  /api/apify/youtube
    query     : 검색어 (예: "마라톤 완주")
    max_items : 최대 결과 수 (기본 10, 최대 50)
    → [{title, url, thumbnail_url, channel, view_count, published_at, description}]

  GET  /api/instagram/posts
    username  : 인스타그램 계정명 (기본 "pac.run")
    limit     : 최대 반환 수 (기본 12)
    → crew.instagram_cache 에서 최신 캐시 조회

  POST /api/instagram/fetch
    username     : 인스타그램 계정명 (기본 "pac.run")
    max_items    : 수집 포스트 수 (기본 12)
    → Apify 실행 → crew.instagram_cache upsert → 저장된 포스트 수 반환

[Apify Actor]
  YouTube  : streamers/youtube-scraper
  Instagram: apify/instagram-scraper

[DB]
  Instagram 캐시는 crew.instagram_cache 에 upsert (post_id 기준 중복 제거)
"""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.services.apify_client import run_actor
from app.core.database import crew_db

router = APIRouter(tags=["apify"])

YOUTUBE_ACTOR = "streamers/youtube-scraper"
INSTAGRAM_ACTOR = "apify/instagram-scraper"


# ─── YouTube ────────────────────────────────────────────────

class YoutubeItem(BaseModel):
    title: str
    url: str
    thumbnail_url: str | None
    channel: str | None
    view_count: int | None
    published_at: str | None
    description: str | None


@router.get("/api/apify/youtube", response_model=list[YoutubeItem])
def search_youtube(
    query: str = Query(..., description="검색어 (예: 마라톤 완주)"),
    max_items: int = Query(10, ge=1, le=50),
):
    try:
        items = run_actor(
            YOUTUBE_ACTOR,
            run_input={"searchKeywords": [query], "maxResults": max_items},
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Apify YouTube 수집 실패: {e}")

    result = []
    for item in items:
        result.append(YoutubeItem(
            title=item.get("title", ""),
            url=item.get("url", ""),
            thumbnail_url=item.get("thumbnailUrl"),
            channel=item.get("channelName") or item.get("channel"),
            view_count=item.get("viewCount"),
            published_at=str(item.get("date") or item.get("publishedAt") or ""),
            description=item.get("description"),
        ))
    return result


# ─── Instagram ───────────────────────────────────────────────

class InstagramFetchRequest(BaseModel):
    username: str = "pac.run"
    max_items: int = 12


class InstagramFetchResponse(BaseModel):
    saved: int
    username: str


def _map_media_type(raw: str | None) -> str:
    mapping = {"Image": "IMAGE", "Video": "VIDEO", "Sidecar": "CAROUSEL_ALBUM"}
    return mapping.get(raw or "", "IMAGE")


@router.get("/api/instagram/posts")
def get_instagram_posts(
    username: str = Query("pac.run"),
    limit: int = Query(12, ge=1, le=50),
):
    try:
        rows = (
            crew_db()
            .table("instagram_cache")
            .select("*")
            .order("posted_at", desc=True)
            .limit(limit)
            .execute()
        )
        return rows.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Instagram 캐시 조회 실패: {e}")


@router.post("/api/instagram/fetch", response_model=InstagramFetchResponse)
def fetch_instagram(req: InstagramFetchRequest):
    try:
        items = run_actor(
            INSTAGRAM_ACTOR,
            run_input={
                "usernames": [req.username],
                "resultsLimit": req.max_items,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Apify Instagram 수집 실패: {e}")

    now = datetime.now(timezone.utc).isoformat()
    records = []
    for item in items:
        post_id = str(item.get("id") or item.get("shortCode") or "")
        if not post_id:
            continue
        media_url = item.get("videoUrl") or item.get("displayUrl") or ""
        records.append({
            "post_id": post_id,
            "media_type": _map_media_type(item.get("type")),
            "media_url": media_url,
            "thumbnail_url": item.get("displayUrl"),
            "caption": (item.get("caption") or "")[:2000],
            "like_count": item.get("likesCount") or 0,
            "comments_count": item.get("commentsCount") or 0,
            "permalink": item.get("url") or f"https://www.instagram.com/p/{item.get('shortCode', '')}/",
            "posted_at": item.get("timestamp"),
            "fetched_at": now,
        })

    if records:
        try:
            crew_db().table("instagram_cache").upsert(
                records,
                on_conflict="post_id",
            ).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Instagram 캐시 저장 실패: {e}")

    return InstagramFetchResponse(saved=len(records), username=req.username)
