import re
import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query
from app.services.race_crawler import crawl_all, crawl_marathongo, crawl_roadrun, HEADERS, MARATHONGO_BASE, _get_next_data
from app.core.database import review_db

router = APIRouter(prefix="/api", tags=["race-info"])


@router.get("/race-info")
def get_race_info(
    source: str = Query(default="all", description="marathongo / roadrun / all"),
    limit: int = Query(default=0, le=200, description="소스별 최대 수집 건수 (0=전체)"),
):
    if source == "marathongo":
        races = crawl_marathongo(limit=limit)
    elif source == "roadrun":
        races = crawl_roadrun(limit=limit)
    else:
        races = crawl_all(limit=limit)

    if not races:
        return {"crawled": 0, "saved": 0, "errors": [], "data": []}

    saved = []
    errors = []
    for race in races:
        record = {k: v for k, v in race.items() if v is not None}
        try:
            result = (
                review_db()
                .table("races")
                .upsert(record, on_conflict="source_url")
                .execute()
            )
            if result.data:
                saved.extend(result.data)
        except Exception as e:
            errors.append({"source_url": race.get("source_url"), "error": str(e)})

    return {
        "crawled": len(races),
        "saved": len(saved),
        "errors": errors,
        "data": saved,
    }


@router.get("/race-info/debug")
def debug_race_crawl():
    """목록 + 첫 번째 상세 페이지 진단"""
    list_url = f"{MARATHONGO_BASE}/raceSchedule/domestic"
    result = {}

    # 1) 목록 페이지
    try:
        resp = requests.get(list_url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        detail_links = soup.find_all("a", href=re.compile(r"/raceDetail/domestic/"))
        next_data = _get_next_data(html)
        result["list"] = {
            "status_code": resp.status_code,
            "html_length": len(html),
            "detail_links_found": len(detail_links),
            "slugs_sample": [
                str(a["href"]).split("/raceDetail/domestic/")[1].rstrip("/")
                for a in detail_links[:3]
            ],
        }
    except Exception as e:
        result["list"] = {"error": str(e)}
        return result

    # 2) 첫 번째 상세 페이지
    if detail_links:
        slug = str(detail_links[0]["href"]).split("/raceDetail/domestic/")[1].rstrip("/")
        detail_url = f"{MARATHONGO_BASE}/raceDetail/domestic/{slug}"
        try:
            resp2 = requests.get(detail_url, headers=HEADERS, timeout=15)
            resp2.encoding = "utf-8"
            html2 = resp2.text
            soup2 = BeautifulSoup(html2, "html.parser")
            next_data2 = _get_next_data(html2)
            h1 = soup2.find("h1")
            text = soup2.get_text(" ", strip=True)
            date_match = re.search(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", text)
            date_match2 = re.search(r"\d{4}[.\-]\d{1,2}[.\-]\d{1,2}", text)
            result["detail"] = {
                "url": detail_url,
                "status_code": resp2.status_code,
                "html_length": len(html2),
                "h1_text": h1.get_text(strip=True) if h1 else None,
                "date_korean_found": date_match.group(0) if date_match else None,
                "date_dot_found": date_match2.group(0) if date_match2 else None,
                "has_next_data": next_data2 is not None,
                "next_data_page_props_keys": list(next_data2.get("props", {}).get("pageProps", {}).keys()) if next_data2 else [],
                "next_data_race_detail": next_data2.get("props", {}).get("pageProps", {}).get("raceDetail") if next_data2 else None,
                "text_preview": text[:300],
            }
        except Exception as e:
            result["detail"] = {"error": str(e)}

    return result


@router.get("/race-info/debug-roadrun-detail")
def debug_roadrun_detail(uid: str = Query(description="roadrun 상세 페이지 uid (예: 1234)")):
    """roadrun.co.kr 상세 팝업 페이지 구조 진단"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    detail_url = f"http://www.roadrun.co.kr/schedule/view.php?uid={uid}"
    try:
        resp = requests.get(detail_url, headers=HEADERS, verify=False, timeout=15)
        resp.encoding = "euc-kr"
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        text = soup.get_text(" ", strip=True)

        # 테이블 행 구조 파악
        rows_info = []
        for tr in soup.find_all("tr")[:30]:
            cells = tr.find_all("td")
            if cells:
                rows_info.append([c.get_text(strip=True)[:40] for c in cells[:4]])

        # 링크 목록
        links = [{"text": a.get_text(strip=True)[:30], "href": a.get("href", "")[:80]} for a in soup.find_all("a")[:10]]

        return {
            "url": detail_url,
            "status_code": resp.status_code,
            "html_length": len(html),
            "text_preview": text[:500],
            "table_rows_sample": rows_info[:20],
            "links": links,
        }
    except Exception as e:
        return {"error": str(e)}
