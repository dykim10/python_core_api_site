"""
RAG 서비스 (app/services/rag_service.py)

race_weather_cases 테이블에 OpenAI 임베딩을 생성·저장하고,
pgvector 코사인 유사도로 유사 케이스를 검색한다.

임베딩 모델: text-embedding-3-small (1536차원, $0.02/1M tokens)
검색 방식  : Supabase RPC → public.match_race_weather_cases(vector)
"""

import logging
from openai import OpenAI
from app.core.config import settings
from app.core.database import review_db, _local, _live

logger = logging.getLogger(__name__)

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM   = 1536


def _openai() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


# ── 텍스트 빌더 ───────────────────────────────────────────────────────────────

def build_case_text(
    race_name: str,
    year: int | None,
    course_type: str | None,
    temperature: float | None,
    humidity: int | None,
    wind_speed: float | None,
    finish_time_seconds: int | None,
) -> str:
    """race_weather_cases 1건을 임베딩할 자연어 텍스트로 변환한다."""
    parts = []

    race_str = race_name
    if year:
        race_str += f" {year}년"
    if course_type:
        label = {"FULL": "풀마라톤 42.195km", "HALF": "하프마라톤 21km", "10K": "10K"}.get(course_type, course_type)
        race_str += f" {label}"
    parts.append(f"대회: {race_str}")

    weather_parts = []
    if temperature is not None:
        weather_parts.append(f"기온 {temperature:.1f}°C")
    if humidity is not None:
        weather_parts.append(f"습도 {humidity}%")
    if wind_speed is not None:
        weather_parts.append(f"바람 {wind_speed:.1f}m/s")
    if weather_parts:
        parts.append(f"날씨: {', '.join(weather_parts)}")

    if finish_time_seconds:
        h, rem = divmod(finish_time_seconds, 3600)
        m, s = divmod(rem, 60)
        parts.append(f"완주기록: {h}시간 {m:02d}분 {s:02d}초")

    return " / ".join(parts)


# ── 임베딩 생성 ───────────────────────────────────────────────────────────────

def generate_embedding(text: str) -> list[float]:
    """텍스트 → 1536차원 벡터 (OpenAI text-embedding-3-small)."""
    resp = _openai().embeddings.create(input=text, model=EMBED_MODEL)
    return resp.data[0].embedding


# ── DB 저장 ───────────────────────────────────────────────────────────────────

def upsert_embedding(case_id: int, embedding: list[float], live: bool = True) -> None:
    """race_weather_cases.embedding 컬럼을 업데이트한다."""
    vector_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
    client = _live() if live else _local()
    client.schema("review").table("race_weather_cases").update(
        {"embedding": vector_str}
    ).eq("id", case_id).execute()


# ── 유사 케이스 검색 ──────────────────────────────────────────────────────────

def search_similar(
    embedding: list[float],
    match_threshold: float = 0.5,
    match_count: int = 5,
    live: bool = True,
) -> list[dict]:
    """
    pgvector HNSW 코사인 유사도로 유사 race_weather_cases를 반환한다.
    Supabase RPC → public.match_race_weather_cases(vector, float, int)
    """
    vector_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
    client = _live() if live else _local()
    result = client.rpc(
        "match_race_weather_cases",
        {
            "query_embedding": vector_str,
            "match_threshold": match_threshold,
            "match_count": match_count,
        },
    ).execute()
    return result.data or []


# ── 통합 헬퍼 ─────────────────────────────────────────────────────────────────

def embed_and_save(case_id: int, text: str, live: bool = True) -> list[float]:
    """임베딩 생성 후 DB 저장까지 한 번에."""
    embedding = generate_embedding(text)
    upsert_embedding(case_id, embedding, live=live)
    logger.info(f"[RAG] case_id={case_id} 임베딩 저장 완료")
    return embedding
