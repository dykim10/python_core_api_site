"""
주간 뉴스레터 테스트 발송 스크립트 (scripts/mailing_test.py)

실행: python scripts/mailing_test.py [--delay 90] [--email <address>] [--now]

--delay N   : N분 후 발송 (기본: 90)
--email X   : 테스트 수신자 이메일
--now       : 즉시 발송 (지연 없음)

예시:
  python scripts/mailing_test.py                    # 90분 후 기본 테스트 이메일로 발송
  python scripts/mailing_test.py --now              # 즉시 발송
  python scripts/mailing_test.py --delay 5 --email test@example.com
"""
import sys
import os
import time
import argparse
from datetime import datetime, timedelta

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.services.mailing_service import send_weekly_mailing

DEFAULT_EMAIL = settings.mailing_test_email or "dykim10iufc@gmail.com"


def main():
    parser = argparse.ArgumentParser(description="주간 뉴스레터 테스트 발송")
    parser.add_argument("--delay", type=int, default=90, help="발송 전 대기 시간(분), 기본 90")
    parser.add_argument("--email", type=str, default=DEFAULT_EMAIL, help="테스트 수신자 이메일")
    parser.add_argument("--now", action="store_true", help="즉시 발송")
    args = parser.parse_args()

    target_email = args.email
    delay_minutes = 0 if args.now else args.delay
    run_at = datetime.now() + timedelta(minutes=delay_minutes)

    if delay_minutes > 0:
        print(f"[PAC RUN CREW 메일링 테스트]")
        print(f"  수신자  : {target_email}")
        print(f"  발송 예정: {run_at.strftime('%Y-%m-%d %H:%M:%S')} ({delay_minutes}분 후)")
        print(f"  대기 중... (Ctrl+C 로 취소)")

        try:
            time.sleep(delay_minutes * 60)
        except KeyboardInterrupt:
            print("\n[취소] 테스트 발송이 취소되었습니다.")
            sys.exit(0)
    else:
        print(f"[PAC RUN CREW 메일링 테스트] 즉시 발송 → {target_email}")

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 발송 시작...")
    try:
        result = send_weekly_mailing(test_email=target_email, live=True)
        if result.get("success"):
            stats = result.get("stats", {})
            print(f"✅ 발송 완료!")
            print(f"   기간   : {stats.get('week_start')} ~ {stats.get('week_end')}")
            print(f"   총 KM  : {stats.get('total_km')} km")
            print(f"   활성   : {stats.get('active_count')}명")
        else:
            print(f"❌ 발송 실패: {result.get('reason')}")
    except Exception as e:
        print(f"❌ 오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
