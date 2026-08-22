from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.services.seed import ensure_admin, seed_all


@pytest.fixture(scope="session", autouse=True)
def _fast_password_hashing():
    """테스트에서는 bcrypt 라운드를 낮춰 실행 시간을 줄인다."""
    from passlib.context import CryptContext

    import app.core.security as security

    security._pwd = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://npo:npo@localhost:5432/npo_sales_test"
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.commit()
    except Exception as exc:  # pragma: no cover - 환경 미비 시 스킵
        pytest.skip(f"테스트 DB에 연결할 수 없습니다: {exc}")
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Session:
    """테스트마다 트랜잭션 롤백으로 격리."""
    connection = engine.connect()
    trans = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False, future=True)()
    seed_all(session)
    yield session
    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture
def admin(db) -> object:
    return ensure_admin(db, "test-admin@example.com", "test1234!")


@pytest.fixture
def client(db):
    """FastAPI TestClient — 세션을 테스트 트랜잭션에 묶는다."""
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.main import app

    class _NoCommitSession:
        """라우터의 commit()이 테스트 트랜잭션을 끝내지 않도록 flush로 대체."""

        def __init__(self, session):
            self._s = session

        def __getattr__(self, name):
            return getattr(self._s, name)

        def commit(self):
            self._s.flush()

    app.dependency_overrides[get_db] = lambda: _NoCommitSession(db)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def auth_headers(client, email: str, password: str) -> dict:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def users(db):
    """ADMIN / MANAGER / SALES 3롤 테스트 계정."""
    from app.core.enums import Role
    from app.core.security import hash_password
    from app.models import User

    made = {}
    for role, email, name, regions in [
        (Role.ADMIN, "admin@test.kr", "관리자", None),
        (Role.MANAGER, "manager@test.kr", "팀장", ["11", "41"]),
        (Role.SALES, "sales@test.kr", "영업사원", ["11"]),
        (Role.SALES, "sales2@test.kr", "영업사원2", ["26"]),
    ]:
        u = User(
            email=email, password_hash=hash_password("test1234!"), name=name,
            role=role, region_codes=regions, is_active=True,
        )
        db.add(u)
        made[email] = u
    db.flush()
    return made
