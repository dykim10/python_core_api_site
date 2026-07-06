"""
AI 코치 서비스 (app/services/coach_service.py)

단건 피드백 / 주간 리포트 / 주간 스케줄 생성.
Claude API 호출 + DB 캐시.
"""
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import anthropic

from app.core.config import settings
from app.core.database import crew_db
from app.core.model_config import model_for
from app.services import body_service
from app.services.vdot import compare_records, training_paces

logger = logging.getLogger(__name__)

FEEDBACK_MODEL = model_for("coach_feedback")
REPORT_MODEL = model_for("coach_weekly_report")
SCHEDULE_MODEL = model_for("coach_schedule")

FEEDBACK_TIMEOUT = 60.0
REPORT_TIMEOUT = 120.0

SYSTEM_PROMPT = """\
당신은 마라톤·러닝 전문 AI 코치입니다. 한국어로 응답합니다.

[훈련 이론 원칙 — 서적 인용 금지, 원칙 요약만 적용]

1. 잭 다니엘스 VDOT: 실제 기록 기반 훈련 페이스(E/M/T/I) 산정. 계산된 존은 숫자로 제공됩니다.
2. 리디아드: 유산소 베이스 우선. 지구력 부족형(endurance_deficit) 진단 시 볼륨 확대 처방.
3. 핏징거: 마라톤 주기화, 미디엄-롱런, LT 훈련 배치.
4. NSM(Norwegian Singles Method): 주 3회 서브-스레숄드 인터벌 + 이지런, 역치 초과 금지.
   여러 이론 중 하나로 참고하며, 심박 데이터가 있으면 역치 초과 여부를 규칙 기반 판정에 반영.

[절대 규칙]
- 개인 식별정보(이름, 이메일, 전화번호) 언급 금지
- JSON 형식으로만 응답 (마크다운 백틱 금지)
- VO2max 시계 값은 절대값이 아닌 추세 참고용
"""


def _parse_claude_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)


def _call_claude(
    model: str,
    system: str,
    user: str,
    timeout: float,
    max_tokens: int = 2048,
) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=timeout)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text = block.text
            break
    try:
        return _parse_claude_json(raw_text)
    except json.JSONDecodeError as e:
        logger.error("[Coach] JSON 파싱 실패")
        raise ValueError("AI 응답 파싱에 실패했습니다.") from e


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _fetch_personal_records(user_id: int) -> list[dict]:
    rows = (
        crew_db()
        .table("personal_records")
        .select("distance_type, record_seconds, achieved_at")
        .eq("user_id", user_id)
        .order("achieved_at", desc=True)
        .execute()
        .data
    ) or []
    seen: set[str] = set()
    latest: list[dict] = []
    for row in rows:
        dt = row["distance_type"]
        if dt in seen:
            continue
        seen.add(dt)
        latest.append(row)
    return latest


def _fetch_running_logs(user_id: int, limit: int = 20, since: date | None = None) -> list[dict]:
    q = (
        crew_db()
        .table("running_logs")
        .select(
            "id, run_date, distance_km, duration_seconds, avg_pace_seconds, "
            "avg_heart_rate, vo2max, user_note, coach_feedback, feedback_at"
        )
        .eq("user_id", user_id)
        .order("run_date", desc=True)
    )
    if since:
        q = q.gte("run_date", since.isoformat())
    rows = q.limit(limit).execute().data or []
    return rows


def _summarize_logs(logs: list[dict]) -> list[dict]:
    return [
        {
            "id": lg.get("id"),
            "run_date": lg.get("run_date"),
            "distance_km": lg.get("distance_km"),
            "avg_pace_seconds": lg.get("avg_pace_seconds"),
            "avg_heart_rate": lg.get("avg_heart_rate"),
            "vo2max": lg.get("vo2max"),
            "user_note": lg.get("user_note"),
        }
        for lg in logs
    ]


def _nsm_threshold_check(log: dict) -> str | None:
    """심박 기반 역치 초과 간단 판정 (165bpm 기준 — 컨텍스트용)."""
    hr = log.get("avg_heart_rate")
    pace = log.get("avg_pace_seconds")
    if hr is None or pace is None:
        return None
    if hr > 165 and pace and pace < 360:
        return f"평균 심박 {hr}bpm — 서브-T 역치(165bpm) 초과 가능성"
    if hr <= 155:
        return f"평균 심박 {hr}bpm — 이지~서브-T 범위 내"
    return f"평균 심박 {hr}bpm — 중간 강도"


def _build_common_context(user_id: int) -> dict[str, Any]:
    records = _fetch_personal_records(user_id)
    vdot_result = compare_records(records)
    paces = {}
    if vdot_result.get("vdots"):
        first_vdot = next(iter(vdot_result["vdots"].values()))
        paces = training_paces(first_vdot)

    recent_logs = _fetch_running_logs(user_id, limit=5)
    vo2max_trend = [
        {"run_date": lg["run_date"], "vo2max": lg.get("vo2max")}
        for lg in recent_logs
        if lg.get("vo2max") is not None
    ]

    return {
        "vdot_analysis": vdot_result,
        "training_paces_sec_per_km": paces,
        "body_trend": body_service.get_body_records_for_context(user_id, limit=3),
        "vo2max_trend": vo2max_trend,
        "recent_logs_summary": _summarize_logs(recent_logs),
    }


def generate_feedback(log_id: int) -> dict[str, Any]:
    """단건 피드백 — feedback_at 캐시."""
    rows = (
        crew_db()
        .table("running_logs")
        .select("*")
        .eq("id", log_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise ValueError(f"러닝 기록(id={log_id})을 찾을 수 없습니다.")
    log = rows[0]

    if log.get("feedback_at") and log.get("coach_feedback"):
        fb = log["coach_feedback"]
        if isinstance(fb, str):
            fb = json.loads(fb)
        return fb

    user_id = log["user_id"]
    two_weeks_ago = date.today() - timedelta(days=14)
    recent = _fetch_running_logs(user_id, limit=30, since=two_weeks_ago)
    context = _build_common_context(user_id)
    nsm = _nsm_threshold_check(log)

    user_prompt = f"""\
대상 러닝 기록:
{json.dumps(_summarize_logs([log])[0], ensure_ascii=False, default=str)}

직전 2주 로그 요약:
{json.dumps(_summarize_logs(recent), ensure_ascii=False, default=str)}

공통 컨텍스트:
{json.dumps(context, ensure_ascii=False, default=str)}

NSM 역치 판정: {nsm or '심박 데이터 없음'}

다음 JSON 형식으로 응답:
{{
  "summary": "한 줄 총평",
  "intensity_check": "강도 적정성 (NSM 역치 판정 포함)",
  "advice": ["조언 1", "조언 2"],
  "next_run": "다음 러닝 권장 방향"
}}
"""
    feedback = _call_claude(FEEDBACK_MODEL, SYSTEM_PROMPT, user_prompt, FEEDBACK_TIMEOUT)

    now = datetime.now().isoformat()
    crew_db().table("running_logs").update({
        "coach_feedback": feedback,
        "feedback_at": now,
    }).eq("id", log_id).execute()

    logger.info(f"[Coach] 피드백 생성 log_id={log_id}")
    return feedback


def _match_point_workout(
    schedule: dict,
    week_logs: list[dict],
) -> tuple[int | None, dict]:
    """스케줄 포인트 훈련과 가장 유사한 로그 매칭."""
    if schedule.get("matched_log_id"):
        matched_id = schedule["matched_log_id"]
        matched = next((lg for lg in week_logs if lg["id"] == matched_id), None)
        return matched_id, matched or {}

    pw = schedule.get("point_workout") or {}
    target_pace = pw.get("target_pace_sec_per_km")
    target_dist = None
    structure = pw.get("structure") or ""
    for km in ("15", "12", "10", "8", "6", "5", "4", "3", "2"):
        if km in structure:
            target_dist = float(km)
            break
    if target_dist is None:
        target_dist = 10.0

    best_id = None
    best_log = None
    best_score = float("inf")

    for lg in week_logs:
        dist = float(lg.get("distance_km") or 0)
        pace = lg.get("avg_pace_seconds")
        dist_err = abs(dist - target_dist)
        pace_err = abs(pace - target_pace) if pace and target_pace else 9999
        score = dist_err * 100 + pace_err
        if score < best_score:
            best_score = score
            best_id = lg["id"]
            best_log = lg

    return best_id, best_log or {}


def generate_weekly_report(user_id: int, week_start: date) -> dict[str, Any]:
    """주간 종합 리포트 — training_reports 캐시."""
    week_start = _monday_of(week_start)
    week_end = week_start + timedelta(days=6)

    cached = (
        crew_db()
        .table("training_reports")
        .select("report")
        .eq("user_id", user_id)
        .eq("period_start", week_start.isoformat())
        .limit(1)
        .execute()
        .data
    )
    if cached:
        report = cached[0]["report"]
        if isinstance(report, str):
            report = json.loads(report)
        return report

    week_logs = (
        crew_db()
        .table("running_logs")
        .select("id, run_date, distance_km, duration_seconds, avg_pace_seconds, avg_heart_rate, vo2max")
        .eq("user_id", user_id)
        .gte("run_date", week_start.isoformat())
        .lte("run_date", week_end.isoformat())
        .execute()
        .data
    ) or []

    total_km = sum(float(lg.get("distance_km") or 0) for lg in week_logs)
    runs = len(week_logs)
    paces = [lg["avg_pace_seconds"] for lg in week_logs if lg.get("avg_pace_seconds")]
    avg_pace = int(sum(paces) / len(paces)) if paces else None
    hrs = [lg["avg_heart_rate"] for lg in week_logs if lg.get("avg_heart_rate")]
    avg_hr = int(sum(hrs) / len(hrs)) if hrs else None

    schedule_rows = (
        crew_db()
        .table("training_schedules")
        .select("*")
        .eq("user_id", user_id)
        .eq("week_start", week_start.isoformat())
        .limit(1)
        .execute()
        .data
    )
    schedule_review = None
    evaluation = None

    if schedule_rows:
        sched = schedule_rows[0]
        matched_id, matched_log = _match_point_workout(sched, week_logs)
        pw = sched.get("point_workout") or {}
        target_pace = pw.get("target_pace_sec_per_km")
        pace_dev = None
        if matched_log and target_pace and matched_log.get("avg_pace_seconds"):
            pace_dev = matched_log["avg_pace_seconds"] - target_pace

        evaluation = {
            "matched_log_id": matched_id,
            "target_pace_sec_per_km": target_pace,
            "actual_pace_sec_per_km": matched_log.get("avg_pace_seconds") if matched_log else None,
            "pace_deviation_sec": pace_dev,
            "point_workout_done": matched_id is not None,
        }
        crew_db().table("training_schedules").update({
            "matched_log_id": matched_id,
            "evaluation": evaluation,
        }).eq("id", sched["id"]).execute()

        schedule_review = evaluation

    context = _build_common_context(user_id)
    user_prompt = f"""\
주간 집계 (period: {week_start} ~ {week_end}):
- 총 거리: {total_km:.1f}km, 횟수: {runs}회
- 평균 페이스: {avg_pace}초/km, 평균 심박: {avg_hr}bpm

주간 로그:
{json.dumps(_summarize_logs(week_logs), ensure_ascii=False, default=str)}

스케줄 대조:
{json.dumps(schedule_review, ensure_ascii=False, default=str) if schedule_review else '해당 주 스케줄 없음'}

공통 컨텍스트:
{json.dumps(context, ensure_ascii=False, default=str)}

다음 JSON 형식으로 응답:
{{
  "week_summary": "주간 총평",
  "volume": {{"total_km": {total_km:.1f}, "runs": {runs}}},
  "schedule_review": {{
    "point_workout_done": true/false,
    "pace_deviation_sec": 숫자 또는 null,
    "comment": "스케줄 대비 코멘트"
  }},
  "trend": "체중/VO2max 추세 코멘트",
  "next_week_focus": "다음 주 방향"
}}
"""
    report = _call_claude(REPORT_MODEL, SYSTEM_PROMPT, user_prompt, REPORT_TIMEOUT, max_tokens=4096)

    if "volume" not in report:
        report["volume"] = {"total_km": round(total_km, 1), "runs": runs}
    if schedule_review and "schedule_review" not in report:
        report["schedule_review"] = {
            "point_workout_done": schedule_review.get("point_workout_done", False),
            "pace_deviation_sec": schedule_review.get("pace_deviation_sec"),
            "comment": "",
        }

    crew_db().table("training_reports").insert({
        "user_id": user_id,
        "period_start": week_start.isoformat(),
        "period_end": week_end.isoformat(),
        "report": report,
    }).execute()

    logger.info(f"[Coach] 주간 리포트 user_id={user_id} week={week_start}")
    return report


def generate_schedule(user_id: int, week_start: date) -> dict[str, Any]:
    """주간 스케줄 생성 — training_schedules 캐시."""
    week_start = _monday_of(week_start)

    cached = (
        crew_db()
        .table("training_schedules")
        .select("point_workout, weekly_volume, rationale")
        .eq("user_id", user_id)
        .eq("week_start", week_start.isoformat())
        .limit(1)
        .execute()
        .data
    )
    if cached:
        row = cached[0]
        return {
            "point_workout": row["point_workout"],
            "weekly_volume": row["weekly_volume"],
            "rationale": row.get("rationale"),
        }

    prev_week = week_start - timedelta(days=7)
    prev_report = (
        crew_db()
        .table("training_reports")
        .select("report")
        .eq("user_id", user_id)
        .eq("period_start", prev_week.isoformat())
        .limit(1)
        .execute()
        .data
    )
    prev_eval = (
        crew_db()
        .table("training_schedules")
        .select("evaluation")
        .eq("user_id", user_id)
        .eq("week_start", prev_week.isoformat())
        .limit(1)
        .execute()
        .data
    )

    context = _build_common_context(user_id)
    prev_context = ""
    if prev_report:
        pr = prev_report[0]["report"]
        if isinstance(pr, str):
            pr = json.loads(pr)
        prev_context += f"\n직전 주 리포트: {json.dumps(pr, ensure_ascii=False, default=str)}"
    if prev_eval and prev_eval[0].get("evaluation"):
        ev = prev_eval[0]["evaluation"]
        prev_context += f"\n직전 주 스케줄 평가: {json.dumps(ev, ensure_ascii=False, default=str)}"

    user_prompt = f"""\
다음 주({week_start}) 훈련 스케줄을 생성하세요.

구성 원칙: **포인트 훈련 1회 + 주간 볼륨 가이드만**. 요일별 7일 계획 금지.

공통 컨텍스트:
{json.dumps(context, ensure_ascii=False, default=str)}
{prev_context}

다음 JSON 형식으로 응답:
{{
  "point_workout": {{
    "type": "sub_threshold_interval",
    "title": "훈련 제목",
    "target_pace_sec_per_km": 280,
    "structure": "웜업 + 본 훈련 + 쿨다운",
    "caution": "주의사항"
  }},
  "weekly_volume": {{"easy_runs": "2~3회", "total_km_min": 25, "total_km_max": 30}},
  "rationale": "이번 주 이 훈련을 처방한 이유"
}}
"""
    schedule = _call_claude(SCHEDULE_MODEL, SYSTEM_PROMPT, user_prompt, REPORT_TIMEOUT, max_tokens=4096)

    crew_db().table("training_schedules").insert({
        "user_id": user_id,
        "week_start": week_start.isoformat(),
        "point_workout": schedule.get("point_workout", {}),
        "weekly_volume": schedule.get("weekly_volume", {}),
        "rationale": schedule.get("rationale"),
    }).execute()

    logger.info(f"[Coach] 스케줄 생성 user_id={user_id} week={week_start}")
    return schedule
