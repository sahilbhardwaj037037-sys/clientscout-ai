"""Persist bounded public website audit runs and evidence."""
from alembic import op
import sqlalchemy as sa
revision = '0002_audits'
down_revision = '0001_leads'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('audits',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('leads.id', ondelete='SET NULL'), nullable=True),
        sa.Column('requested_url', sa.String(2048), nullable=False),
        sa.Column('hostname', sa.String(300), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('progress', sa.String(200), nullable=False),
        sa.Column('pagespeed_requested', sa.Boolean(), nullable=False),
        sa.Column('pagespeed_attempted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_allowed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('error_code', sa.String(50), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('report', sa.JSON(), nullable=True),
        sa.CheckConstraint("status IN ('queued','running','complete','partial','error','blocked','cancelled','interrupted')", name='audit_status'),
    )
    op.create_index('ix_audits_hostname', 'audits', ['hostname'])


def downgrade():
    op.drop_index('ix_audits_hostname', table_name='audits')
    op.drop_table('audits')
