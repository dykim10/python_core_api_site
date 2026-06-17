"""
RAG 엔드포인트 (app/api/routes/rag.py)

race_weather_cases 임베딩 저장 및 유사 케이스 검색 API.
레이스 플랜 생성 시 REVIEW가 호출한다.

엔드포인트:
  POST /api/rag/embed   — 케이스 텍스트 임베딩 생성 + race_weather_cases 저장
  POST /api/rag/search  — 쿼리 텍스트 → 유사 케이스 목록 반환
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import rag_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rag", tags=["rag"])


# ── 요청 / 응답 스키마 ────────────────────────────────────────────────────────

class EmbedRequest(BaseModel):
    case_id:             int
    race_name:           str
    year:                int | None = None
    course_type:         str | None = Field(None, pattern="^(FULL|HALF|10K)$")
    temperature:         float | None = None
    humidity:            int | None = None
    wind_speed:          float | None = None
    finish_time_seconds: int | None = None
    live:                bool = True


class EmbedResponse(BaseModel):
    case_id: int
    dim:     int


class SearchRequest(BaseModel):
    race_name:           str
    year:                int | None = None
    course_type:         str | None = Field(None, pattern="^(FULL|HALF|10K)$")
    temperature:         float | None = None
    humidity:            int | None = None
    wind_speed:          float | None = None
    finish_time_seconds: int | None = None
    match_threshold:     float = Field(0.5, ge=0.0, le=1.0)
    match_count:         int   = Field(5, ge=1, le=20)
    live:                bool  = True


class SearchResponse(BaseModel):
    results: list[dict]
    count:   int


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("/embed", response_model=EmbedResponse)
def embed_case(req: EmbedRequest):
    """
    race_weather_cases 1건의 텍스트 임베딩을 생성하고 DB에 저장한다.
    REVIEW가 리뷰 등록 직후 또는 날씨 연동 완료 후 호출한다.
    """
    text = rag_service.build_case_text(
        race_name=req.race_name,
        year=req.year,
        course_type=req.course_type,
        temperature=req.temperature,
        humidity=req.humidity,
        wind_speed=req.wind_speed,
        finish_time_seconds=req.finish_time_seconds,
    )
    try:
        embedding = rag_service.embed_and_save(req.case_id, text, live=req.live)
    except Exception as e:
        logger.error(f"[RAG] 임베딩 저장 실패 case_id={req.case_id}: {e}")
        raise HTTPException(status_code=500, detail=f"임베딩 저장 실패: {str(e)}")

    return EmbedResponse(case_id=req.case_id, dim=len(embedding))


@router.post("/search", response_model=SearchResponse)
def search_cases(req: SearchRequest):
    """
    쿼리 조건(날씨 + 코스 + 목표기록)을 텍스트화해 임베딩 후 유사 케이스를 검색한다.
    레이스 플랜 생성 API에서 호출한다.
    """
    text = rag_service.build_case_text(
        race_name=req.race_name,
        year=req.year,
        course_type=req.course_type,
        temperature=req.temperature,
        humidity=req.humidity,
        wind_speed=req.wind_speed,
        finish_time_seconds=req.finish_time_seconds,
    )
    try:
        embedding = rag_service.generate_embedding(text)
        results   = rag_service.search_similar(
            embedding,
            match_threshold=req.match_threshold,
            match_count=req.match_count,
            live=req.live,
        )
    except Exception as e:
        logger.error(f"[RAG] 유사 케이스 검색 실패: {e}")
        raise HTTPException(status_code=500, detail=f"검색 실패: {str(e)}")

    return SearchResponse(results=results, count=len(results))
