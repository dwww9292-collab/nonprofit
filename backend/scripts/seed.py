"""시드 실행 스크립트.

    python -m scripts.seed            # 소스/배점/앱설정/관리자 계정만
    python -m scripts.seed --demo     # + 데모 사용자·리드 30건·딜·활동
    python -m scripts.seed --reset-scoring   # 배점을 문서 기본값으로 되돌림
"""

from __future__ import annotations

import argparse

from app.core.db import SessionLocal
from app.services.demo_data import DEMO_USERS, create_demo_data
from app.services.seed import ensure_admin, seed_all, seed_scoring


def main() -> None:
    parser = argparse.ArgumentParser(description="NPO Sales Radar 시드")
    parser.add_argument("--demo", action="store_true", help="데모 데이터까지 생성")
    parser.add_argument("--reset-scoring", action="store_true", help="스코어링 배점을 기본값으로 덮어쓰기")
    parser.add_argument("--demo-count", type=int, default=30, help="생성할 데모 리드 수")
    args = parser.parse_args()

    with SessionLocal() as db:
        stats = seed_all(db)
        if args.reset_scoring:
            seed_scoring(db, overwrite=True)
            print("스코어링 배점을 문서 기본값으로 재설정했습니다.")
        admin = ensure_admin(db)
        print(f"기본 시드 완료: {stats}")
        print(f"관리자 계정: {admin.email} / 비밀번호는 .env의 ADMIN_PASSWORD 값입니다")

        if args.demo:
            demo = create_demo_data(db, args.demo_count)
            password = demo.pop("demo_password")
            print(f"데모 데이터 생성: {demo}")
            print(f"데모 계정({', '.join(e for e, *_ in DEMO_USERS)}) 비밀번호: {password}")

        db.commit()


if __name__ == "__main__":
    main()
