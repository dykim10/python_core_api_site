"""
SNS 수집 라우터 (app/api/routes/sns.py)

대회(race_edition_id) 기준 YouTube / Instagram 콘텐츠 수집 및 캐시 조회.

엔드포인트:
  POST /api/sns/youtube/fetch          — YouTube 수집 + review.youtube_cache upsert
  POST /api/sns/instagram/fetch        — Instagram 수집 + review.instagram_cache upsert
  GET  /api/sns/youtube/{edition_id}   — YouTube 캐시 목록 반환
  GET  /api/sns/instagram/{edition_id} — Instagram 캐시 목록 반환

임베딩:
  POST /api/sns/youtube/{edition_id}/embed   — YouTube 항목 임베딩
  POST /api/sns/instagram/{edition_id}/embed — Instagram 항목 임베딩
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.database import review_db
from app.services import sns_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sns", tags=["sns"])


# ── 요청 스키마 ───────────────────────────────────────────────────────────────

class FetchRequest(BaseModel):
    race_edition_id: int
    max_items:       int = 20
    live:            bool = True
    embed:           bool = False   # 수집 직후 임베딩 여부


class FetchResponse(BaseModel):
    saved: int
    embedded: int = 0


# ── YouTube ───────────────────────────────────────────────────────────────────

@router.post("/youtube/fetch", response_model=FetchResponse)
def fetch_youtube(req: FetchRequest):
    """YouTube 수집 → review.youtube_cache upsert."""
    try:
        saved = sns_service.fetch_youtube(req.race_edition_id, req.max_items, req.live)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[SNS] YouTube 수집 실패: {e}")
        raise HTTPException(status_code=500, detail=f"YouTube 수집 실패: {str(e)}")

    embedded = 0
    if req.embed and saved > 0:
        try:
            embedded = sns_service.embed_youtube_cache(req.race_edition_id, req.live)
        except Exception as e:
            logger.warning(f"[SNS] YouTube 임베딩 실패 (무시): {e}")

    return FetchResponse(saved=saved, embedded=embedded)


@router.get("/youtube/{race_edition_id}")
def get_youtube(
    race_edition_id: int,
    limit: int = Query(20, ge=1, le=100),
    live: bool = Query(True),
):
    """review.youtube_cache 목록 반환."""
    try:
        rows = review_db(live).table("youtube_cache") \
            .select("id, video_id, title, url, thumbnail_url, view_count, published_at") \
            .eq("race_edition_id", race_edition_id) \
            .order("published_at", desc=True) \
            .limit(limit) \
            .execute().data
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"YouTube 캐시 조회 실패: {str(e)}")


@router.post("/youtube/{race_edition_id}/embed")
def embed_youtube(race_edition_id: int, live: bool = Query(True)):
    """임베딩 없는 YouTube 캐시 항목을 일괄 임베딩."""
    try:
        count = sns_service.embed_youtube_cache(race_edition_id, live)
        return {"embedded": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Instagram ─────────────────────────────────────────────────────────────────

@router.post("/instagram/fetch", response_model=FetchResponse)
def fetch_instagram(req: FetchRequest):
    """Instagram 수집 → review.instagram_cache upsert."""
    try:
        saved = sns_service.fetch_instagram(req.race_edition_id, req.max_items, req.live)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[SNS] Instagram 수집 실패: {e}")
        raise HTTPException(status_code=500, detail=f"Instagram 수집 실패: {str(e)}")

    embedded = 0
    if req.embed and saved > 0:
        try:
            embedded = sns_service.embed_instagram_cache(req.race_edition_id, req.live)
        except Exception as e:
            logger.warning(f"[SNS] Instagram 임베딩 실패 (무시): {e}")

    return FetchResponse(saved=saved, embedded=embedded)


@router.get("/instagram/{race_edition_id}")
def get_instagram(
    race_edition_id: int,
    limit: int = Query(12, ge=1, le=50),
    live: bool = Query(True),
):
    """review.instagram_cache 목록 반환."""
    try:
        rows = review_db(live).table("instagram_cache") \
            .select("id, post_id, caption, thumbnail_url, permalink, like_count, posted_at") \
            .eq("race_edition_id", race_edition_id) \
            .order("posted_at", desc=True) \
            .limit(limit) \
            .execute().data
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Instagram 캐시 조회 실패: {str(e)}")


@router.post("/instagram/{race_edition_id}/embed")
def embed_instagram(race_edition_id: int, live: bool = Query(True)):
    """임베딩 없는 Instagram 캐시 항목을 일괄 임베딩."""
    try:
        count = sns_service.embed_instagram_cache(race_edition_id, live)
        return {"embedded": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
