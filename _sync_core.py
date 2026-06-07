"""
_sync_core.py — sync_crew.py / sync_review.py 공통 코어

직접 실행하지 않음. sync_crew.py / sync_review.py 에서 import 하여 사용.
"""
import base64
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    print("requests 패키지 필요: pip install requests")
    sys.exit(1)

PAGE_SIZE = 1000


class SupabaseRest:
    def __init__(self, url: str, service_role_key: str, label: str):
        self.base  = url.rstrip("/") + "/rest/v1"
        self.label = label
        self._s    = requests.Session()
        self._s.headers.update({
            "apikey":        service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type":  "application/json",
        })

    def fetch_all(self, schema: str, table: str) -> list[dict]:
        rows:   list[dict] = []
        offset: int        = 0
        extra = {"Accept-Profile": schema} if schema != "public" else {}

        while True:
            resp = self._s.get(
                f"{self.base}/{table}",
                headers={**extra, "Range": f"{offset}-{offset + PAGE_SIZE - 1}"},
                params={"select": "*"},
                timeout=30,
            )
            if resp.status_code == 416:
                break
            resp.raise_for_status()
            chunk: list[dict] = resp.json()
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        return rows

    def upsert(self, schema: str, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0

        headers = {"Prefer": "resolution=merge-duplicates,return=representation"}
        if schema != "public":
            headers["Content-Profile"] = schema

        written = 0
        for i in range(0, len(rows), PAGE_SIZE):
            chunk = rows[i : i + PAGE_SIZE]
            resp  = self._s.post(
                f"{self.base}/{table}",
                json=chunk,
                headers=headers,
                timeout=60,
            )
            if resp.status_code not in (200, 201):
                print(f"\n    upsert 오류 {resp.status_code}: {resp.text[:300]}")
                continue
            written += len(chunk)

        return written


def sync(
    live:     SupabaseRest,
    local:    SupabaseRest,
    targets:  list[tuple[str, str]],
    dry_run:  bool,
) -> tuple[int, list[tuple[str, str]]]:
    total  = 0
    errors: list[tuple[str, str]] = []

    for schema, table in targets:
        label = f"{schema}.{table}"
        try:
            print(f"  {'[DRY]' if dry_run else '     '} {label:<42}", end="", flush=True)
            t0   = time.time()
            rows = live.fetch_all(schema, table)
            print(f"{len(rows):>5}건 ({time.time()-t0:.1f}s)", end="")

            if dry_run:
                print()
                total += len(rows)
                continue

            t1      = time.time()
            written = local.upsert(schema, table, rows)
            print(f"  -> {written:>5}건 upsert ({time.time()-t1:.1f}s)")
            total += written

        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                print("  -- 테이블 없음 (스킵)")
            else:
                code = exc.response.status_code if exc.response is not None else "?"
                print(f"\n    HTTP {code}: {exc}")
                errors.append((label, str(exc)))
        except Exception as exc:
            print(f"\n    오류: {exc}")
            errors.append((label, str(exc)))

    return total, errors


def _decode_jwt_payload(token: str) -> dict:
    try:
        parts  = token.split(".")
        if len(parts) != 3:
            return {}
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


def check_connections(live_url_var: str, live_key_var: str,
                      local_url_var: str = "SUPABASE_URL",
                      local_key_var: str = "SUPABASE_SERVICE_ROLE_KEY") -> bool:
    ok = True
    pairs = [("LIVE", live_url_var, live_key_var), ("LOCAL", local_url_var, local_key_var)]

    for label, url_var, key_var in pairs:
        url = os.getenv(url_var, "")
        key = os.getenv(key_var, "")

        print(f"\n[{label}]")
        print(f"  URL : {url or '(미설정)'}")
        print(f"  KEY : {key[:12]}...{key[-6:] if len(key) > 18 else '(짧음)'}")

        if not key:
            print("  키가 비어 있습니다.")
            ok = False
            continue

        payload   = _decode_jwt_payload(key)
        role      = payload.get("role", "알 수 없음")
        role_ok   = role == "service_role"
        role_mark = "OK" if role_ok else "WARNING"
        print(f"  JWT role : [{role_mark}] {role}")

        try:
            resp = requests.get(
                url.rstrip("/") + "/rest/v1/",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                timeout=10,
            )
            status = "OK" if resp.status_code == 200 else f"FAIL {resp.status_code}"
            print(f"  연결 테스트 : {status}")
            if resp.status_code != 200:
                ok = False
        except Exception as e:
            print(f"  연결 테스트 실패: {e}")
            ok = False

    return ok


def make_clients(live_url_var: str, live_key_var: str) -> tuple[SupabaseRest, SupabaseRest]:
    live_url  = os.getenv(live_url_var,  "")
    live_key  = os.getenv(live_key_var,  "")
    local_url = os.getenv("SUPABASE_URL", "")
    local_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    missing = [v for v, val in [
        (live_url_var,  live_url),
        (live_key_var,  live_key),
        ("SUPABASE_URL", local_url),
        ("SUPABASE_SERVICE_ROLE_KEY", local_key),
    ] if not val]

    if missing:
        print(f".env 누락 변수: {', '.join(missing)}")
        sys.exit(1)

    return (
        SupabaseRest(live_url,  live_key,  "LIVE"),
        SupabaseRest(local_url, local_key, "LOCAL"),
    )
