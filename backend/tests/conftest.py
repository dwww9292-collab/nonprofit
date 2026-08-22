from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.services.seed import ensure_admin, seed_all

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
