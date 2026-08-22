"""API 스키마 (Pydantic v2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import (
    ActivityType,
    AssetSize,
    DealStage,
    LeadStatus,
    LostReason,
    OrgType,
    ProductCode,
    Role,
)

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


# --- auth / users ---


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserOut(ORMModel):
    id: int
    email: str
    name: str
    role: Role
    region_codes: list[str] | None = None
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=50)
    role: Role = Role.SALES
    region_codes: list[str] | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    role: Role | None = None
    region_codes: list[str] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


# --- leads ---


class SourceOut(ORMModel):
    id: int
    code: str
    name: str
    collect_method: str
    is_active: bool
    license_type: str | None = None
    crawl_note: str | None = None


class LeadListItem(ORMModel):
    id: int
    org_name: str
    org_type: OrgType
    region_code: str | None
    district: str | None
    established_at: date | None
    designated_at: date | None
    stage_signal: str
    score: int
    grade: str
    status: LeadStatus
    assignee_id: int | None
    assignee_name: str | None = None
    source_code: str | None = None
    collected_at: datetime
    is_existing_customer: bool
    possible_dup_lead_id: int | None
    possible_revoked: bool


class LeadDetail(LeadListItem):
    org_name_norm: str
    corp_reg_no: str | None
    biz_reg_no: str | None
    address: str | None
    representative: str | None
    phone: str | None
    email: str | None
    homepage_url: str | None
    purpose: str | None
    authority: str | None
    memo: str | None
    asset_size: AssetSize
    score_breakdown: dict[str, Any] | None
    lost_reason: LostReason | None
    assigned_at: datetime | None
    first_contacted_at: datetime | None
    sources: list[SourceOut] = []


class LeadCreateManual(BaseModel):
    org_name: str = Field(min_length=1, max_length=200)
    org_type: OrgType
    source_code: str
    address: str | None = None
    region_code: str | None = None
    district: str | None = None
    representative: str | None = None
    phone: str | None = None
    email: str | None = None
    homepage_url: str | None = None
    established_at: date | None = None
    designated_at: date | None = None
    purpose: str | None = None
    authority: str | None = None
    corp_reg_no: str | None = None
    biz_reg_no: str | None = None
    asset_size: AssetSize = AssetSize.UNKNOWN
    memo: str | None = None


class LeadUpdate(BaseModel):
    org_name: str | None = None
    org_type: OrgType | None = None
    address: str | None = None
    region_code: str | None = None
    district: str | None = None
    representative: str | None = None
    phone: str | None = None
    email: str | None = None
    homepage_url: str | None = None
    established_at: date | None = None
    designated_at: date | None = None
    purpose: str | None = None
    authority: str | None = None
    corp_reg_no: str | None = None
    biz_reg_no: str | None = None
    asset_size: AssetSize | None = None
    memo: str | None = None


class LeadStatusUpdate(BaseModel):
    status: LeadStatus
    lost_reason: LostReason | None = None
    memo: str | None = None


class LeadAssignRequest(BaseModel):
    lead_ids: list[int] = Field(min_length=1)
    assignee_id: int


class LeadBulkStatusRequest(BaseModel):
    lead_ids: list[int] = Field(min_length=1)
    status: LeadStatus
    lost_reason: LostReason | None = None


class DupCheckRequest(BaseModel):
    org_name: str
    address: str | None = None
    corp_reg_no: str | None = None
    biz_reg_no: str | None = None


class DupCandidate(BaseModel):
    lead_id: int
    org_name: str
    address: str | None
    region_code: str | None
    status: str
    assignee_name: str | None
    match_reason: str


class DupCheckResponse(BaseModel):
    exact: DupCandidate | None = None
    similar: list[DupCandidate] = []
    existing_customer: bool = False


class AssigneeSuggestion(BaseModel):
    user_id: int
    name: str
    region_match: bool
    open_lead_count: int


# --- deals ---


class DealOut(ORMModel):
    id: int
    lead_id: int
    lead_name: str | None = None
    product_code: ProductCode
    stage: DealStage
    amount: int | None
    probability: int | None
    expected_close: date | None
    closed_at: datetime | None
    lost_reason: LostReason | None
    owner_id: int
    owner_name: str | None = None
    next_action_at: datetime | None = None


class DealCreate(BaseModel):
    lead_id: int
    product_code: ProductCode
    stage: DealStage = DealStage.CONTACT
    amount: int | None = None
    probability: int | None = None
    expected_close: date | None = None
    owner_id: int | None = None


class DealUpdate(BaseModel):
    product_code: ProductCode | None = None
    stage: DealStage | None = None
    amount: int | None = None
    probability: int | None = None
    expected_close: date | None = None
    lost_reason: LostReason | None = None
    owner_id: int | None = None


# --- activities ---


class ActivityOut(ORMModel):
    id: int
    lead_id: int
    deal_id: int | None
    type: ActivityType
    summary: str
    next_action: str | None
    next_action_at: datetime | None
    actor_id: int
    actor_name: str | None = None
    occurred_at: datetime


class ActivityCreate(BaseModel):
    type: ActivityType
    summary: str = Field(min_length=1)
    deal_id: int | None = None
    next_action: str | None = None
    next_action_at: datetime | None = None
    occurred_at: datetime | None = None


# --- ingest ---


class PreviewResponse(BaseModel):
    header_map: dict[str, str]
    unmapped_headers: list[str]
    sheet_name: str | None
    total_rows: int
    is_first_upload: bool
    duplicate_file: bool
    preview_rows: list[dict]
    problems: list[str]


class IngestResponse(BaseModel):
    batch_id: int | None
    status: str
    total_rows: int
    new_leads: int
    merged_leads: int
    dup_skipped: int
    customer_skipped: int
    error_rows: int
    revoked_marked: int = 0
    is_first_upload: bool = False
    warnings: list[str] = []
    errors: list[dict] = []


class CustomerUploadResponse(BaseModel):
    total_rows: int
    inserted: int
    updated: int
    error_rows: int
    retagged_leads: int
    errors: list[dict] = []


class BatchOut(ORMModel):
    id: int
    source_code: str | None = None
    source_name: str | None = None
    file_name: str | None
    period_label: str | None
    status: str
    total_rows: int
    new_leads: int
    merged_leads: int
    dup_skipped: int
    customer_skipped: int
    error_rows: int
    error_message: str | None
    created_at: datetime


# --- dashboard / performance ---


class DashboardLeadBrief(BaseModel):
    id: int
    org_name: str
    score: int
    grade: str
    collected_at: datetime
    assignee_name: str | None = None
    days_since_assigned: int | None = None


class WeeklyPoint(BaseModel):
    week: str
    source_code: str
    count: int


class StageSummary(BaseModel):
    stage: str
    count: int
    amount: int


class ProductSummary(BaseModel):
    product_code: str
    count: int
    amount: int


class DashboardResponse(BaseModel):
    urgent_unassigned_count: int
    urgent_unassigned: list[DashboardLeadBrief]
    stale_assigned_count: int
    stale_assigned: list[DashboardLeadBrief]
    weekly_inflow: list[WeeklyPoint]
    grade_distribution: dict[str, int]
    pipeline_summary: list[StageSummary]
    quarter_won: list[ProductSummary]
    quarter_label: str


class PerformanceRow(BaseModel):
    user_id: int
    name: str
    assigned_leads: int
    contacted_leads: int
    contact_rate: float
    meetings: int
    proposals: int
    won_count: int
    won_amount: int
    avg_first_contact_hours: float | None


class PerformanceResponse(BaseModel):
    period_label: str
    rows: list[PerformanceRow]
    product_summary: list[ProductSummary]


# --- settings ---


class ScoringSettingOut(ORMModel):
    id: int
    rule_key: str
    points: int
    description: str | None
    value_json: dict[str, Any] | None


class ScoringSettingUpdate(BaseModel):
    points: int | None = None
    value_json: dict[str, Any] | None = None


class RescoreResponse(BaseModel):
    updated: int


class AppSettingOut(ORMModel):
    key: str
    value: dict[str, Any]


class SourceUpdate(BaseModel):
    is_active: bool | None = None
    license_type: str | None = None
    crawl_note: str | None = None


TokenResponse.model_rebuild()
