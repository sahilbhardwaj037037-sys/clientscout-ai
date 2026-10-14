"""Separate licensed discovery staging, cache and selected OSM business records."""
from alembic import op
import sqlalchemy as sa
revision = '0003_discovery'
down_revision = '0002_audits'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('discovery_searches',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('query', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('progress', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cooldown_until', sa.DateTime(timezone=True), nullable=False), sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error', sa.String(1000), nullable=True),
        sa.CheckConstraint("status IN ('queued','running','complete','error','cancelled','interrupted')", name='discovery_status'))
    op.create_table('discovery_cache', sa.Column('key', sa.String(64), primary_key=True), sa.Column('value', sa.JSON(), nullable=False), sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('discovered_businesses', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('provider', sa.String(40), nullable=False),
        sa.Column('source_id', sa.String(80), nullable=False), sa.Column('data', sa.JSON(), nullable=False), sa.Column('saved_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider', 'source_id', name='uq_business_source'))


def downgrade():
    op.drop_table('discovered_businesses'); op.drop_table('discovery_cache'); op.drop_table('discovery_searches')
