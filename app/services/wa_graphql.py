"""
World Athletics GraphQL 클라이언트 (Label Road Races 캘린더·주최자 정보).

공식 Next.js 클라이언트와 동일 엔드포인트 사용:
  POST https://graphql-prod-4875.edge.aws.worldathletics.org/graphql
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

WA_GRAPHQL_URL = "https://graphql-prod-4875.edge.aws.worldathletics.org/graphql"
WA_LABEL_GROUP_ID = 3775
WA_CALENDAR_BASE = (
    "https://worldathletics.org/competitions/world-athletics-label-road-races/calendar-results"
)

MINISITE_CALENDAR_QUERY = """
query getMinisiteCalendarEvents(
  $competitionGroupId: Int
  $competitionSubgroupId: Int
  $season: String
) {
  getMinisiteCalendarEvents(
    competitionGroupId: $competitionGroupId
    competitionSubgroupId: $competitionSubgroupId
    season: $season
  ) {
    parameters {
      season
      competitionGroupId
      competitionSubgroupId
    }
    results {
      id
      iaafId
      hasResults
      hasCompetitionInformation
      disciplines
      rankingCategory
      competitionSubgroup
      name
      venue
      country
      startDate
      endDate
      dateRange
    }
  }
}
"""

ORGANISER_QUERY = """
query GetCompetitionOrganiserInfo($competitionId: Int!) {
  getCompetitionOrganiserInfo(competitionId: $competitionId) {
    websiteUrl
    resultsPageUrl
    liveStreamingUrl
    additionalInfo
    contactPersons {
      name
      email
      phoneNumber
      title
    }
  }
}
"""


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Origin": "https://worldathletics.org",
        "Referer": WA_CALENDAR_BASE,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "X-Api-Key": settings.wa_graphql_api_key,
    }


def graphql_request(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    resp = requests.post(
        WA_GRAPHQL_URL,
        json={"query": query, "variables": variables},
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(f"WA GraphQL errors: {payload['errors']}")
    return payload["data"]


def fetch_minisite_calendar(
    season: int | str,
    *,
    subgroup_id: int = 0,
) -> list[dict[str, Any]]:
    """시즌별 Label Road Races 캘린더 목록."""
    data = graphql_request(
        MINISITE_CALENDAR_QUERY,
        {
            "competitionGroupId": WA_LABEL_GROUP_ID,
            "competitionSubgroupId": subgroup_id,
            "season": str(season),
        },
    )
    block = data.get("getMinisiteCalendarEvents") or {}
    results = block.get("results") or []
    logger.info(
        "WA calendar season=%s subgroup=%s → %d events",
        season,
        subgroup_id,
        len(results),
    )
    return results


def fetch_organiser_info(competition_id: int) -> Optional[dict[str, Any]]:
    """대회 주최자·공식 URL (organiser 아이콘 모달과 동일 데이터)."""
    try:
        data = graphql_request(
            ORGANISER_QUERY,
            {"competitionId": competition_id},
        )
        return data.get("getCompetitionOrganiserInfo")
    except Exception as e:
        logger.warning("WA organiser fetch failed id=%s: %s", competition_id, e)
        return None


def result_page_url(competition_id: int) -> str:
    return f"{WA_CALENDAR_BASE}/{competition_id}/result"
