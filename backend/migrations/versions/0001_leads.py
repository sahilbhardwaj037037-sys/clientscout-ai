"""Persist user-supplied leads; no provider evidence, scoring or drafts."""
from alembic import op
import sqlalchemy as sa

revision = '0001_leads'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'leads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('business_name', sa.String(200), nullable=False),
        sa.Column('website_url', sa.String(2048), nullable=False),
        sa.Column('normalized_key', sa.String(300), nullable=False),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('location', sa.String(200), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('source_filename', sa.String(200), nullable=True),
        sa.Column('original_url', sa.String(2048), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('normalized_key', name='uq_leads_normalized_key'),
        sa.CheckConstraint("status IN ('new', 'shortlisted', 'contacted', 'won', 'archived')", name='lead_status'),
        sa.CheckConstraint("source IN ('manual', 'csv')", name='lead_source'),
    )


def downgrade():
    op.drop_table('leads')
