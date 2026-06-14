"""
주간 메일링 서비스 (app/services/mailing_service.py)

매주 월요일 06:00 KST 에 APScheduler 가 호출하여
지난 한 주간 CREW 구성원의 러닝 통계를 집계한 뉴스레터를 발송한다.

[주요 함수]
  get_weekly_stats(live)     → 지난 7일 러닝 통계 집계
  get_recipients(live)       → 인증된 구성원 이메일 복호화 목록
  build_weekly_html(stats)   → 뉴스레터 HTML 생성
  send_weekly_mailing(...)   → 집계 → HTML 빌드 → Resend 발송
"""
import logging
from datetime import datetime, timedelta

from app.core.database import crew_db, public_db
from app.services.email_service import send_email
from app.utils.crypto import decrypt

logger = logging.getLogger(__name__)


# ── 통계 집계 ─────────────────────────────────────────────────────────────────

def get_weekly_stats(live: bool = True) -> dict:
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    week_ago_str = week_ago.isoformat()

    try:
        logs_res = (
            crew_db(live)
            .table("running_logs")
            .select("user_id,distance_km")
            .eq("is_confirmed", True)
            .gte("created_at", week_ago_str)
            .execute()
        )
        logs = logs_res.data or []
    except Exception as e:
        logger.error(f"[메일링] 러닝 로그 조회 실패: {e}")
        logs = []

    user_km: dict[int, float] = {}
    for log in logs:
        uid = log.get("user_id")
        km = float(log.get("distance_km") or 0)
        if uid:
            user_km[uid] = user_km.get(uid, 0) + km

    total_km = sum(user_km.values())
    active_count = len(user_km)
    top3_ids = sorted(user_km, key=lambda u: user_km[u], reverse=True)[:3]

    top3 = []
    if top3_ids:
        try:
            users_res = (
                public_db(live)
                .table("users")
                .select("id,nickname")
                .in_("id", top3_ids)
                .execute()
            )
            user_map = {
                u["id"]: (u.get("nickname") or "러너")
                for u in (users_res.data or [])
            }
            for rank, uid in enumerate(top3_ids, start=1):
                top3.append({
                    "rank": rank,
                    "name": user_map.get(uid, "러너"),
                    "km": round(user_km[uid], 1),
                })
        except Exception as e:
            logger.error(f"[메일링] 사용자 조회 실패: {e}")

    return {
        "total_km": round(total_km, 1),
        "active_count": active_count,
        "total_logs": len(logs),
        "top3": top3,
        "week_start": week_ago.strftime("%Y.%m.%d"),
        "week_end": now.strftime("%Y.%m.%d"),
        "issue_date": now.strftime("%Y년 %m월 %d일"),
        "week_num": now.isocalendar()[1],
    }


# ── 수신자 조회 ───────────────────────────────────────────────────────────────

def get_recipients(live: bool = True) -> list[str]:
    try:
        res = (
            public_db(live)
            .table("users")
            .select("email_enc,email_verified_at")
            .not_.is_("email_verified_at", "null")
            .not_.is_("email_enc", "null")
            .execute()
        )
        users = res.data or []
    except Exception as e:
        logger.error(f"[메일링] 수신자 조회 실패: {e}")
        return []

    emails = []
    for u in users:
        try:
            email = decrypt(u.get("email_enc"))
            if email:
                emails.append(email)
        except Exception:
            pass

    return emails


# ── HTML 빌드 ─────────────────────────────────────────────────────────────────

def build_weekly_html(stats: dict) -> str:
    total_km = stats.get("total_km", 0)
    active_count = stats.get("active_count", 0)
    top3 = stats.get("top3", [])
    week_start = stats.get("week_start", "")
    week_end = stats.get("week_end", "")
    issue_date = stats.get("issue_date", "")
    week_num = stats.get("week_num", "")

    avg_km = round(total_km / active_count, 1) if active_count > 0 else 0

    # 순위 아이콘
    rank_icons = ["🥇", "🥈", "🥉"]

    # 리더보드 행 (KM 비율 진행 바 포함)
    leaderboard_rows = ""
    max_km = top3[0]['km'] if top3 else 1
    for entry in top3:
        icon = rank_icons[entry["rank"] - 1] if entry["rank"] <= 3 else f"#{entry['rank']}"
        pct = max(4, int((entry['km'] / max_km) * 100))
        leaderboard_rows += f"""
        <tr>
          <td style="padding:18px 0 18px 20px;border-bottom:1px solid #1A1818;width:44px;vertical-align:top;">
            <span style="font-family:'Bebas Neue',sans-serif;font-size:28px;color:#E5AD16;line-height:1;">{entry['rank']}</span>
          </td>
          <td style="padding:18px 10px;border-bottom:1px solid #1A1818;">
            <span style="font-size:14px;font-weight:500;color:#FFFFFF;line-height:1;display:block;">{icon}&ensp;{entry['name']}</span>
            <div style="margin-top:10px;background-color:#222;height:2px;">
              <div style="background-color:#E5AD16;height:2px;width:{pct}%;"></div>
            </div>
          </td>
          <td style="padding:18px 20px 18px 8px;border-bottom:1px solid #1A1818;text-align:right;vertical-align:top;white-space:nowrap;">
            <span style="font-family:'Bebas Neue',sans-serif;font-size:28px;color:#E5AD16;line-height:1;">{entry['km']}</span>
            <span style="font-size:9px;color:#3A3030;letter-spacing:2px;display:block;margin-top:4px;">KM</span>
          </td>
        </tr>"""

    if not leaderboard_rows:
        leaderboard_rows = """
        <tr>
          <td colspan="3" style="padding:32px 20px;text-align:center;color:#333;font-size:13px;letter-spacing:1px;">
            이번 주 러닝 기록이 없습니다. 달려볼까요? 🏃
          </td>
        </tr>"""

    motivational = _pick_motivational(week_num)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CREW WEEKLY DISPATCH — {issue_date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  * {{ margin:0;padding:0;box-sizing:border-box; }}
  body {{ background-color:#0C0C0C;font-family:'Noto Sans KR',-apple-system,sans-serif;-webkit-font-smoothing:antialiased; }}
</style>
</head>
<body>
<div style="background-color:#0C0C0C;padding:40px 20px;">
<div style="max-width:600px;margin:0 auto;background-color:#141010;">

  <!-- 상단 골드 라인 -->
  <div style="height:3px;background-color:#E5AD16;"></div>

  <!-- 헤더 -->
  <div style="background-color:#141010;padding:20px 40px;border-bottom:1px solid #1F1C1C;">
    <table style="width:100%;border-collapse:collapse;">
      <tr>
        <td style="vertical-align:middle;">
          <span style="font-family:'Bebas Neue',sans-serif;font-size:22px;letter-spacing:5px;color:#E5AD16;line-height:1;">PAC RUN</span>
          <span style="font-family:'Bebas Neue',sans-serif;font-size:16px;color:#2A2020;padding:0 10px;">/</span>
          <span style="font-family:'Bebas Neue',sans-serif;font-size:10px;letter-spacing:4px;color:#3D3535;">CREW · SINCE 2024</span>
        </td>
        <td style="text-align:right;vertical-align:middle;">
          <span style="font-family:'Bebas Neue',sans-serif;font-size:9px;letter-spacing:4px;color:#3A3030;">ISSUE #{week_num}</span>
        </td>
      </tr>
    </table>
  </div>

  <!-- 히어로 배너 -->
  <div style="background-color:#0F0D0D;padding:48px 40px 40px;position:relative;overflow:hidden;border-bottom:3px solid #E5AD16;">
    <div style="position:absolute;bottom:-20px;right:-10px;font-family:'Bebas Neue',sans-serif;font-size:180px;color:transparent;-webkit-text-stroke:1px rgba(229,173,22,0.05);letter-spacing:0;line-height:1;pointer-events:none;">W</div>

    <div style="margin-bottom:24px;">
      <span style="font-family:'Bebas Neue',sans-serif;font-size:10px;letter-spacing:5px;color:#3A3030;margin-right:10px;">WK</span>
      <span style="display:inline-block;width:28px;height:1px;background-color:#2A2020;vertical-align:middle;margin-right:10px;"></span>
      <span style="display:inline-block;background-color:#E5AD16;color:#0F0D0D;font-family:'Bebas Neue',sans-serif;font-size:10px;letter-spacing:4px;padding:5px 14px;">WEEKLY DISPATCH</span>
    </div>

    <div style="font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:2px;color:#FFFFFF;line-height:1;">
      CREW<br><span style="color:#E5AD16;">WEEKLY</span>
    </div>

    <div style="margin-top:20px;padding-top:16px;border-top:1px solid #1F1C1C;">
      <span style="font-family:'Bebas Neue',sans-serif;font-size:10px;letter-spacing:3px;color:#2E2828;">{week_start} — {week_end} · {issue_date} 발행</span>
    </div>
  </div>

  <!-- 이번 주 요약 카드 -->
  <div style="background-color:#FFFFFF;padding:44px 40px 36px;">

    <span style="font-family:'Bebas Neue',sans-serif;font-size:10px;letter-spacing:5px;color:#E5AD16;display:block;margin-bottom:24px;">— 이번 주 크루 현황</span>

    <table style="width:100%;border-collapse:collapse;border-spacing:0;margin-bottom:32px;" role="presentation">
      <tr>
        <td style="width:34%;padding-right:7px;vertical-align:top;">
          <div style="background-color:#0F0D0D;padding:22px 16px;">
            <div style="font-family:'Bebas Neue',sans-serif;font-size:9px;letter-spacing:4px;color:#333;margin-bottom:8px;">TOTAL KM</div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:48px;color:#E5AD16;line-height:1;">{total_km}</div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:10px;color:#444;letter-spacing:3px;margin-top:6px;">KM THIS WEEK</div>
          </div>
        </td>
        <td style="width:33%;padding-right:4px;padding-left:3px;vertical-align:top;">
          <div style="background-color:#F8F8F6;border:1px solid #ECECEA;padding:22px 16px;">
            <div style="font-family:'Bebas Neue',sans-serif;font-size:9px;letter-spacing:4px;color:#888;margin-bottom:8px;">RUNNERS</div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:48px;color:#1A1212;line-height:1;">{active_count}</div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:10px;color:#888;letter-spacing:3px;margin-top:6px;">MEMBERS</div>
          </div>
        </td>
        <td style="width:33%;padding-left:7px;vertical-align:top;">
          <div style="background-color:#F8F8F6;border:1px solid #ECECEA;padding:22px 16px;">
            <div style="font-family:'Bebas Neue',sans-serif;font-size:9px;letter-spacing:4px;color:#888;margin-bottom:8px;">AVG / MEMBER</div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:48px;color:#1A1212;line-height:1;">{avg_km}</div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:10px;color:#888;letter-spacing:3px;margin-top:6px;">KM AVG</div>
          </div>
        </td>
      </tr>
    </table>

    <!-- 리더보드 -->
    <span style="font-family:'Bebas Neue',sans-serif;font-size:10px;letter-spacing:5px;color:#E5AD16;display:block;margin-bottom:16px;">— 이번 주 TOP RUNNERS</span>

    <table style="width:100%;border-collapse:collapse;background-color:#0F0D0D;margin-bottom:36px;">
      <tr>
        <td colspan="3" style="padding:10px 16px;background-color:#141010;border-bottom:1px solid #1A1818;">
          <span style="font-family:'Bebas Neue',sans-serif;font-size:9px;letter-spacing:4px;color:#3A3030;">RANK</span>
        </td>
      </tr>
      {leaderboard_rows}
    </table>

    <!-- 동기부여 메시지 -->
    <div style="background-color:#0F0D0D;padding:24px 28px;border-left:3px solid #E5AD16;margin-bottom:0;">
      <div style="font-family:'Bebas Neue',sans-serif;font-size:9px;letter-spacing:5px;color:#E5AD16;margin-bottom:12px;">THIS WEEK'S WORD</div>
      <div style="font-size:14px;font-weight:300;color:#B0A898;line-height:1.9;">{motivational}</div>
    </div>

  </div>

  <!-- CTA -->
  <div style="background-color:#EDEBE5;padding:28px 40px;border-top:1px solid #DDD8C8;text-align:center;">
    <a href="https://crew.pac-run.com/running-logs/create"
       style="display:inline-block;background-color:#E5AD16;color:#0F0D0D;font-family:'Bebas Neue',sans-serif;font-size:16px;letter-spacing:6px;padding:18px 52px;text-decoration:none;border-bottom:4px solid #B8881A;">
      이번 주 기록 업로드하기
    </a>
    <div style="margin-top:14px;">
      <a href="https://crew.pac-run.com" style="font-size:11px;color:#A09880;text-decoration:none;letter-spacing:2px;">크루 홈페이지 방문하기 →</a>
    </div>
  </div>

  <!-- 푸터 -->
  <div style="background-color:#0F0D0D;padding:28px 40px;border-top:3px solid #E5AD16;">
    <table style="width:100%;border-collapse:collapse;">
      <tr>
        <td style="vertical-align:bottom;">
          <span style="font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:5px;color:#E5AD16;display:block;">PAC RUN CREW</span>
          <span style="font-family:'Bebas Neue',sans-serif;font-size:9px;letter-spacing:4px;color:#2A2020;display:block;margin-top:4px;">EST. 2024</span>
        </td>
        <td style="text-align:right;vertical-align:bottom;">
          <a href="https://crew.pac-run.com" style="font-size:11px;color:#3D3535;text-decoration:none;letter-spacing:1px;display:block;line-height:2;">홈페이지</a>
          <a href="https://crew.pac-run.com/boards/qna" style="font-size:11px;color:#3D3535;text-decoration:none;letter-spacing:1px;display:block;line-height:2;">문의하기</a>
        </td>
      </tr>
    </table>
    <div style="margin-top:16px;padding-top:14px;border-top:1px solid #1A1818;font-size:9px;color:#2A2020;letter-spacing:2px;text-align:center;">
      © {datetime.now().year} PAC RUN. ALL RIGHTS RESERVED. &nbsp;|&nbsp; 매주 월요일 오전 6시 발송
    </div>
  </div>

</div>
</div>
</body>
</html>"""


def _pick_motivational(week_num: int) -> str:
    messages = [
        "달리기는 몸을 단련하는 것이 아니라, 멈추지 않는 법을 배우는 것입니다. 이번 주도 크루와 함께 달려주셔서 감사합니다.",
        "페이스보다 중요한 것은 포기하지 않는 마음입니다. 작은 한 걸음이 쌓여 결승선이 됩니다.",
        "새벽의 출발선 위에서 당신은 이미 대부분의 사람보다 앞서 있습니다. PAC RUN과 함께라서 더 빠릅니다.",
        "땀 한 방울이 기록이 되고, 기록 하나가 습관이 되고, 습관이 쌓여 러너가 됩니다.",
        "가장 느린 사람도 소파에 앉아있는 사람보다는 빠릅니다. 오늘도 달렸다면 당신은 이미 승자입니다.",
        "크루와 함께하는 러닝은 혼자보다 30% 더 오래 달리게 만듭니다. 이번 주도 PAC CREW가 함께합니다.",
        "기록보다 더 중요한 건 꾸준함입니다. 오늘 달린 당신이 내일의 대회를 만듭니다.",
        "완주하는 사람은 포기한 사람을 영원히 이깁니다. 이번 주 달린 모든 크루에게 박수를 보냅니다.",
        "고통은 일시적이지만 기록은 영원합니다. 이번 주도 PAC RUN CREW와 함께 달려주셔서 감사합니다.",
        "러닝은 목적지가 아닙니다. 달리는 동안 당신이 이미 도착해 있습니다.",
        "마라톤의 진짜 경쟁자는 어제의 나 자신입니다. 오늘의 당신은 어제보다 강합니까?",
        "비가 와도, 바람이 불어도, 우리는 달립니다. 그것이 PAC RUN CREW입니다.",
    ]
    return messages[week_num % len(messages)]


# ── 발송 진입점 ───────────────────────────────────────────────────────────────

def send_weekly_mailing(
    test_email: str | None = None,
    live: bool = True,
) -> dict:
    """
    주간 뉴스레터 발송.

    test_email 이 주어지면 해당 주소 1건에만 발송 (테스트 모드).
    test_email 이 None 이면 DB 에서 수신자 목록을 가져와 전체 발송.
    """
    stats = get_weekly_stats(live=live)
    html = build_weekly_html(stats)
    subject = f"[PAC RUN CREW] 이번 주 크루 달리기 현황 — {stats['week_start']} ~ {stats['week_end']}"

    if test_email:
        recipients = [test_email]
        logger.info(f"[메일링] 테스트 발송 → {test_email}")
    else:
        recipients = get_recipients(live=live)
        logger.info(f"[메일링] 전체 발송 시작 — {len(recipients)}명")

    if not recipients:
        logger.warning("[메일링] 수신자 없음 — 발송 중단")
        return {"success": False, "reason": "수신자 없음", "stats": stats}

    results = []
    failed = 0
    for email in recipients:
        try:
            result = send_email(email, subject, html)
            results.append({"email": email, "id": getattr(result, "id", None)})
        except Exception as e:
            logger.error(f"[메일링] 발송 실패 ({email}): {e}")
            failed += 1

    sent = len(results) - failed
    logger.info(f"[메일링] 완료 — 성공 {sent} / 실패 {failed}")

    return {
        "success": True,
        "sent": sent,
        "failed": failed,
        "stats": stats,
        "test_mode": test_email is not None,
    }
