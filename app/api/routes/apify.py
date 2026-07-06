"""
Apify 크롤링 라우터 (app/api/routes/apify.py)

YouTube 영상 검색과 Instagram 포스트 수집을 Apify Actor 로 처리한다.

[엔드포인트]

  GET  /api/apify/youtube
    query     : 검색어 (예: "마라톤 완주")
    max_items : 최대 결과 수 (기본 10, 최대 50)
    → [{title, url, thumbnail_url, channel, view_count, published_at, description}]

  GET  /api/instagram/posts
    limit     : 최대 반환 수 (기본 12)
    → crew.instagram_cache 에서 최신 캐시 조회

  POST /api/instagram/fetch
    username     : 인스타그램 계정명 (기본 pac_run)
    max_items    : 수집 포스트 수 (기본 12)
    → Apify 실행 → crew.instagram_cache upsert → 저장된 포스트 수 반환

[Apify Actor]
  YouTube  : streamers/youtube-scraper
  Instagram: apify/instagram-scraper

[DB]
  Instagram 캐시는 crew.instagram_cache 에 upsert (post_id 기준 중복 제거)
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.services.apify_client import run_actor
from app.services import instagram_service

router = APIRouter(tags=["apify"])

YOUTUBE_ACTOR = "streamers/youtube-scraper"


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
    username: str = "pac_run"
    max_items: int = 12


class InstagramFetchResponse(BaseModel):
    saved: int
    username: str


@router.get("/api/instagram/posts")
def get_instagram_posts(
    limit: int = Query(12, ge=1, le=50),
):
    try:
        return instagram_service.list_crew_instagram(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Instagram 캐시 조회 실패: {e}") from e


@router.post("/api/instagram/fetch", response_model=InstagramFetchResponse)
def fetch_instagram(req: InstagramFetchRequest):
    try:
        saved = instagram_service.fetch_crew_instagram(
            username=req.username,
            max_items=req.max_items,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Apify Instagram 수집 실패: {e}") from e

    return InstagramFetchResponse(saved=saved, username=req.username.lstrip("@"))
