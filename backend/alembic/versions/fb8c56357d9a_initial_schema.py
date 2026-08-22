"""initial schema

Revision ID: fb8c56357d9a
Revises: 
Create Date: 2026-08-22 09:23:49.408085
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'fb8c56357d9a'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 유사도 기반 중복의심 판정(docs/01-schema.md 중복판정 4)에 pg_trgm 필요
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=50), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('existing_customers',
    sa.Column('org_name', sa.String(length=200), nullable=False),
    sa.Column('org_name_norm', sa.String(length=200), nullable=False),
    sa.Column('corp_reg_no', sa.String(length=20), nullable=True),
    sa.Column('biz_reg_no', sa.String(length=12), nullable=True),
    sa.Column('region_code', sa.String(length=10), nullable=True),
    sa.Column('address', sa.String(length=300), nullable=True),
    sa.Column('products', sa.ARRAY(sa.String(length=20)), nullable=True),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_existing_customers_biz_reg_no'), 'existing_customers', ['biz_reg_no'], unique=False)
    op.create_index(op.f('ix_existing_customers_corp_reg_no'), 'existing_customers', ['corp_reg_no'], unique=False)
    op.create_index(op.f('ix_existing_customers_org_name_norm'), 'existing_customers', ['org_name_norm'], unique=False)
    op.create_table('scoring_settings',
    sa.Column('rule_key', sa.String(length=50), nullable=False),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=200), nullable=True),
    sa.Column('value_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('rule_key')
    )
    op.create_table('sources',
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('collect_method', sa.String(length=20), nullable=False),
    sa.Column('license_type', sa.String(length=20), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('crawl_allowed', sa.Boolean(), nullable=True),
    sa.Column('crawl_note', sa.String(length=300), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('users',
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('region_codes', sa.ARRAY(sa.String(length=10)), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('failed_login_count', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('audit_logs',
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('target_type', sa.String(length=20), nullable=True),
    sa.Column('target_id', sa.BigInteger(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_user_created', 'audit_logs', ['user_id', 'created_at'], unique=False)
    op.create_table('ingest_batches',
    sa.Column('source_id', sa.BigInteger(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('file_hash', sa.String(length=64), nullable=True),
    sa.Column('period_label', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('total_rows', sa.Integer(), nullable=False),
    sa.Column('new_leads', sa.Integer(), nullable=False),
    sa.Column('merged_leads', sa.Integer(), nullable=False),
    sa.Column('dup_skipped', sa.Integer(), nullable=False),
    sa.Column('customer_skipped', sa.Integer(), nullable=False),
    sa.Column('error_rows', sa.Integer(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('uploaded_by', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('leads',
    sa.Column('org_name', sa.String(length=200), nullable=False),
    sa.Column('org_name_norm', sa.String(length=200), nullable=False),
    sa.Column('org_type', sa.String(length=30), nullable=False),
    sa.Column('corp_reg_no', sa.String(length=20), nullable=True),
    sa.Column('biz_reg_no', sa.String(length=12), nullable=True),
    sa.Column('region_code', sa.String(length=10), nullable=True),
    sa.Column('district', sa.String(length=50), nullable=True),
    sa.Column('address', sa.String(length=300), nullable=True),
    sa.Column('representative', sa.String(length=50), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('homepage_url', sa.String(length=300), nullable=True),
    sa.Column('established_at', sa.Date(), nullable=True),
    sa.Column('designated_at', sa.Date(), nullable=True),
    sa.Column('purpose', sa.Text(), nullable=True),
    sa.Column('authority', sa.String(length=100), nullable=True),
    sa.Column('memo', sa.Text(), nullable=True),
    sa.Column('asset_size', sa.String(length=20), nullable=False),
    sa.Column('stage_signal', sa.String(length=30), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('score_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('grade', sa.String(length=1), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('lost_reason', sa.String(length=30), nullable=True),
    sa.Column('assignee_id', sa.BigInteger(), nullable=True),
    sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('first_contacted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_existing_customer', sa.Boolean(), nullable=False),
    sa.Column('possible_dup_lead_id', sa.BigInteger(), nullable=True),
    sa.Column('possible_revoked', sa.Boolean(), nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=False),
    sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('score >= 0 AND score <= 100', name='ck_leads_score_range'),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['possible_dup_lead_id'], ['leads.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('biz_reg_no'),
    sa.UniqueConstraint('corp_reg_no')
    )
    op.create_index('ix_leads_collected_at', 'leads', ['collected_at'], unique=False)
    op.create_index(
        'ix_leads_grade_score',
        'leads',
        ['grade', sa.text('score DESC')],
        unique=False,
    )
    op.create_index(
        'ix_leads_org_name_norm_trgm',
        'leads',
        ['org_name_norm'],
        unique=False,
        postgresql_using='gin',
        postgresql_ops={'org_name_norm': 'gin_trgm_ops'},
    )
    op.create_index('ix_leads_norm_region', 'leads', ['org_name_norm', 'region_code'], unique=False)
    op.create_index(op.f('ix_leads_org_name_norm'), 'leads', ['org_name_norm'], unique=False)
    op.create_index('ix_leads_status_assignee', 'leads', ['status', 'assignee_id'], unique=False)
    op.create_table('deals',
    sa.Column('lead_id', sa.BigInteger(), nullable=False),
    sa.Column('product_code', sa.String(length=20), nullable=False),
    sa.Column('stage', sa.String(length=20), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=True),
    sa.Column('probability', sa.SmallInteger(), nullable=True),
    sa.Column('expected_close', sa.Date(), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lost_reason', sa.String(length=30), nullable=True),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_deals_stage_owner', 'deals', ['stage', 'owner_id'], unique=False)
    op.create_table('lead_sources',
    sa.Column('lead_id', sa.BigInteger(), nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=False),
    sa.Column('batch_id', sa.BigInteger(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['ingest_batches.id'], ),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lead_id', 'source_id', 'batch_id', name='uq_lead_source_batch')
    )
    op.create_table('raw_records',
    sa.Column('batch_id', sa.BigInteger(), nullable=False),
    sa.Column('row_no', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('lead_id', sa.BigInteger(), nullable=True),
    sa.Column('dedup_result', sa.String(length=20), nullable=False),
    sa.Column('match_key', sa.String(length=300), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['ingest_batches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_raw_records_batch_matchkey', 'raw_records', ['batch_id', 'match_key'], unique=False)
    op.create_table('activities',
    sa.Column('lead_id', sa.BigInteger(), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=True),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('next_action', sa.String(length=200), nullable=True),
    sa.Column('next_action_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('actor_id', sa.BigInteger(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_activities_lead_occurred', 'activities', ['lead_id', 'occurred_at'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_activities_lead_occurred', table_name='activities')
    op.drop_table('activities')
    op.drop_index('ix_raw_records_batch_matchkey', table_name='raw_records')
    op.drop_table('raw_records')
    op.drop_table('lead_sources')
    op.drop_index('ix_deals_stage_owner', table_name='deals')
    op.drop_table('deals')
    op.drop_index('ix_leads_status_assignee', table_name='leads')
    op.drop_index(op.f('ix_leads_org_name_norm'), table_name='leads')
    op.drop_index('ix_leads_norm_region', table_name='leads')
    op.drop_index('ix_leads_org_name_norm_trgm', table_name='leads')
    op.drop_index('ix_leads_grade_score', table_name='leads')
    op.drop_index('ix_leads_collected_at', table_name='leads')
    op.drop_table('leads')
    op.drop_table('ingest_batches')
    op.drop_index('ix_audit_user_created', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('users')
    op.drop_table('sources')
    op.drop_table('scoring_settings')
    op.drop_index(op.f('ix_existing_customers_org_name_norm'), table_name='existing_customers')
    op.drop_index(op.f('ix_existing_customers_corp_reg_no'), table_name='existing_customers')
    op.drop_index(op.f('ix_existing_customers_biz_reg_no'), table_name='existing_customers')
    op.drop_table('existing_customers')
    op.drop_table('app_settings')
    # ### end Alembic commands ###
