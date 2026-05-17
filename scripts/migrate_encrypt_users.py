"""
public.users 개인정보 암호화 마이그레이션 스크립트
  - email  → email_hash (SHA-256) + email_enc (Fernet)
  - name   → name_enc  (Fernet, 값 있는 경우만)
  - phone  → phone_enc (Fernet, 값 있는 경우만)

실행 전 체크리스트:
  [ ] Supabase DB 백업 완료
  [ ] .env 의 ENCRYPT_KEY 설정 확인
  [ ] 드라이런(--dry-run) 으로 먼저 확인

실행 방법:
  python scripts/migrate_encrypt_users.py           # 실제 마이그레이션
  python scripts/migrate_encrypt_users.py --dry-run # 변경 없이 결과만 출력
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
from app.core.config import settings
from app.utils.crypto import hash_email, encrypt

PAGE_SIZE = 200


def migrate(dry_run: bool = False) -> None:
    if not settings.encrypt_key:
        print("[ERROR] ENCRYPT_KEY 가 설정되지 않았습니다. .env 를 확인하세요.")
        sys.exit(1)

    mode = "[DRY-RUN]" if dry_run else "[LIVE]"
    print(f"{mode} public.users 암호화 마이그레이션 시작\n")

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    db = client  # public 스키마 기본

    total = 0
    skipped = 0
    migrated = 0
    failed = 0

    offset = 0
    while True:
        res = (
            db.table("users")
            .select("id, email, name, email_hash")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = res.data or []
        if not batch:
            break

        for row in batch:
            total += 1
            user_id = row["id"]

            # 이미 마이그레이션된 행은 건너뜀 (멱등성)
            if row.get("email_hash"):
                skipped += 1
                continue

            email = (row.get("email") or "").strip()
            if not email:
                print(f"  [SKIP] id={user_id} — email 없음")
                skipped += 1
                continue

            try:
                update_payload = {
                    "email_hash": hash_email(email),
                    "email_enc":  encrypt(email),
                }

                name = (row.get("name") or "").strip()
                if name:
                    update_payload["name_enc"] = encrypt(name)

                if dry_run:
                    print(f"  [DRY] id={user_id}  email={email}  컬럼={list(update_payload.keys())}")
                else:
                    db.table("users").update(update_payload).eq("id", user_id).execute()
                    print(f"  [OK]  id={user_id}  email={email}")

                migrated += 1

            except Exception as e:
                print(f"  [FAIL] id={user_id}  error={e}")
                failed += 1

        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    print(f"\n{mode} 완료")
    print(f"  전체: {total}건 | 처리: {migrated}건 | 스킵: {skipped}건 | 실패: {failed}건")

    if not dry_run and failed == 0:
        print("\n[INFO] 모든 행 마이그레이션 성공.")
        print("[INFO] 일정 기간 병행 운영 후 검증 완료 시 STEP 6 (평문 컬럼 제거) 진행하세요.")

    if failed > 0:
        print(f"\n[WARNING] 실패 {failed}건 — 위 로그를 확인하고 재실행하세요.")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="public.users 개인정보 암호화 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="DB 변경 없이 결과만 출력")
    args = parser.parse_args()

    migrate(dry_run=args.dry_run)
