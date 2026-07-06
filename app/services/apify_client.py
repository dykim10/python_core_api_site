"""
Apify 클라이언트 유틸 (app/services/apify_client.py)

Apify actor 를 실행하고 결과 데이터셋을 반환하는 공통 헬퍼.
API 키는 settings.apify_api_key 에서 읽는다.

[함수]
  run_actor(actor_id, run_input, timeout_secs) → list[dict]
    actor 를 동기 실행(call)하고 defaultDataset 의 모든 아이템을 반환한다.
    timeout_secs 초 안에 완료되지 않으면 ApifyClientError 가 발생한다.

[호출처]
  apify.py → YouTube / Instagram 크롤링
"""
from datetime import timedelta

from apify_client import ApifyClient
from app.core.config import settings


def _run_dataset_id(run) -> str | None:
    """Apify Run 객체(dict / pydantic 모델) 모두 지원."""
    if run is None:
        return None
    if isinstance(run, dict):
        return run.get("defaultDatasetId") or run.get("default_dataset_id")
    return getattr(run, "default_dataset_id", None) or getattr(run, "defaultDatasetId", None)


def run_actor(actor_id: str, run_input: dict, timeout_secs: int = 180) -> list[dict]:
    client = ApifyClient(settings.apify_api_key)
    run = client.actor(actor_id).call(
        run_input=run_input,
        wait_duration=timedelta(seconds=timeout_secs),
    )
    dataset_id = _run_dataset_id(run)
    if not dataset_id:
        return []
    page = client.dataset(dataset_id).list_items()
    return list(page.items) if page and page.items else []
