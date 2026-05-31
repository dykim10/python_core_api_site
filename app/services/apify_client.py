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
from apify_client import ApifyClient
from app.core.config import settings


def run_actor(actor_id: str, run_input: dict, timeout_secs: int = 180) -> list[dict]:
    client = ApifyClient(settings.apify_api_key)
    run = client.actor(actor_id).call(run_input=run_input, timeout_secs=timeout_secs)
    return list(client.dataset(run["defaultDatasetId"]).iterate_items())
