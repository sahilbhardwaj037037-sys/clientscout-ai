"""Add nullable diagnostic evidence without rewriting historic discovery/lead data."""
from alembic import op
import sqlalchemy as sa
revision = '0004_discovery_diagnostics'
down_revision = '0003_discovery'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('discovery_searches',sa.Column('diagnostics',sa.JSON(),nullable=True))

def downgrade():
    with op.batch_alter_table('discovery_searches') as batch:
        batch.drop_column('diagnostics')
