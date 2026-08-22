"""docs/01-schema.md 전체 테이블 정의."""

from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AssetSize,
    BatchStatus,
    DedupResult,
    DealStage,
    LeadStatus,
    Role,
    StageSignal,
)
from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=Role.SALES)
    region_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 로그인 실패 5회 → 5분 잠금 (docs/05-screens.md)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    collect_method: Mapped[str] = mapped_column(String(20), nullable=False)
    license_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 1차 고도화(크롤러) 대비 — docs/04-data-sources.md
    crawl_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    crawl_note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class IngestBatch(TimestampMixin, Base):
    __tablename__ = "ingest_batches"

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    period_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BatchStatus.PENDING)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_leads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    merged_leads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dup_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    customer_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    source: Mapped[Source] = relationship(lazy="joined")


class RawRecord(TimestampMixin, Base):
    __tablename__ = "raw_records"

    batch_id: Mapped[int] = mapped_column(ForeignKey("ingest_batches.id", ondelete="CASCADE"), nullable=False)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    dedup_result: Mapped[str] = mapped_column(String(20), nullable=False, default=DedupResult.NEW)
    # diff 매칭 키 (기재부 누계 비교용): corp_reg_no 또는 org_name_norm|address_norm
    match_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_raw_records_batch_matchkey", "batch_id", "match_key"),)


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    org_name: Mapped[str] = mapped_column(String(200), nullable=False)
    org_name_norm: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    org_type: Mapped[str] = mapped_column(String(30), nullable=False)
    corp_reg_no: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    biz_reg_no: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    district: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    representative: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 개인정보
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    homepage_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    established_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    designated_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    authority: Mapped[str | None] = mapped_column(String(100), nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_size: Mapped[str] = mapped_column(String(20), nullable=False, default=AssetSize.UNKNOWN)
    stage_signal: Mapped[str] = mapped_column(String(30), nullable=False, default=StageSignal.UNKNOWN)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    grade: Mapped[str] = mapped_column(String(1), nullable=False, default="D")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=LeadStatus.NEW)
    lost_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_existing_customer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 유사도 중복의심 (자동병합 안 함, 배지만 — docs/01-schema.md 중복판정 4)
    possible_dup_lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    # 기재부 누계에서 사라진 행 → 지정취소 가능성 (docs/04-data-sources.md)
    possible_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")
    source: Mapped[Source] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_leads_norm_region", "org_name_norm", "region_code"),
        Index("ix_leads_status_assignee", "status", "assignee_id"),
        Index("ix_leads_grade_score", "grade", "score"),
        Index("ix_leads_collected_at", "collected_at"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_leads_score_range"),
    )


class LeadSource(TimestampMixin, Base):
    __tablename__ = "lead_sources"

    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("ingest_batches.id"), nullable=True)

    __table_args__ = (UniqueConstraint("lead_id", "source_id", "batch_id", name="uq_lead_source_batch"),)


class Deal(TimestampMixin, Base):
    __tablename__ = "deals"

    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    product_code: Mapped[str] = mapped_column(String(20), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default=DealStage.CONTACT)
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    probability: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    expected_close: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    lead: Mapped[Lead] = relationship(lazy="joined")
    owner: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (Index("ix_deals_stage_owner", "stage", "owner_id"),)


class Activity(TimestampMixin, Base):
    __tablename__ = "activities"

    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    next_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    actor: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (Index("ix_activities_lead_occurred", "lead_id", "occurred_at"),)


class ExistingCustomer(TimestampMixin, Base):
    __tablename__ = "existing_customers"

    org_name: Mapped[str] = mapped_column(String(200), nullable=False)
    org_name_norm: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    corp_reg_no: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    biz_reg_no: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    region_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    products: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ScoringSetting(TimestampMixin, Base):
    __tablename__ = "scoring_settings"

    rule_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # REGION.CORE 목록 등 JSON 설정값 (docs/03-scoring.md 4번 주석)
    value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AppSetting(TimestampMixin, Base):
    """단순 key-value 앱 설정 (예: 지역 기반 배정 제안 토글)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (Index("ix_audit_user_created", "user_id", "created_at"),)
