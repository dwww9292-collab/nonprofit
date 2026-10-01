"""leads에 NSM 고객 마스터 매칭 결과 추가

Revision ID: a1b2c3d4e5f6
Revises: fb8c56357d9a
Create Date: 2026-10-01

영업사원이 '이 단체가 실제로 어떤 더존 제품을 쓰는가'로 리드를 걸러야 하므로,
매칭 결과를 leads에 직접 둔다(목록 필터가 조인 없이 돌아간다).
nsm_product_families 는 JSONB 배열이고 GIN 인덱스로 포함 검색(@>)을 받는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "fb8c56357d9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("nsm_matched", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("leads", sa.Column("nsm_match_confidence", sa.String(length=10), nullable=True))
    op.add_column("leads", sa.Column("nsm_match_basis", sa.String(length=160), nullable=True))
    op.add_column("leads", sa.Column("nsm_company_name", sa.String(length=200), nullable=True))
    op.add_column("leads", sa.Column("nsm_customer_code", sa.String(length=30), nullable=True))
    op.add_column("leads", sa.Column("nsm_biz_reg_no", sa.String(length=12), nullable=True))
    op.add_column("leads", sa.Column("nsm_products", sa.String(length=300), nullable=True))
    op.add_column("leads", sa.Column("nsm_product_families", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("leads", sa.Column("nsm_top_product", sa.String(length=40), nullable=True))
    op.add_column("leads", sa.Column("nsm_product_tier", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("leads", sa.Column("nsm_sales_owner", sa.String(length=50), nullable=True))
    op.add_column("leads", sa.Column("upsell_path", sa.String(length=80), nullable=True))
    op.add_column("leads", sa.Column("upsell_priority", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("nsm_synced_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_leads_upsell", "leads", ["upsell_priority", "nsm_product_tier"])
    # 보유 제품 필터는 JSONB 배열 포함 검색이므로 GIN 이어야 한다
    op.create_index(
        "ix_leads_nsm_families",
        "leads",
        ["nsm_product_families"],
        postgresql_using="gin",
    )

    # server_default 는 기존 행을 채우기 위한 것이므로, 채운 뒤에는 떼어낸다
    # (이후 삽입은 모델 기본값이 담당한다).
    op.alter_column("leads", "nsm_matched", server_default=None)
    op.alter_column("leads", "nsm_product_tier", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_leads_nsm_families", table_name="leads")
    op.drop_index("ix_leads_upsell", table_name="leads")
    for col in (
        "nsm_synced_at",
        "upsell_priority",
        "upsell_path",
        "nsm_sales_owner",
        "nsm_product_tier",
        "nsm_top_product",
        "nsm_product_families",
        "nsm_products",
        "nsm_biz_reg_no",
        "nsm_customer_code",
        "nsm_company_name",
        "nsm_match_basis",
        "nsm_match_confidence",
        "nsm_matched",
    ):
        op.drop_column("leads", col)
