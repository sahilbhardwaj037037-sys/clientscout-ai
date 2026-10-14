"""Persist asynchronous AI request controls without storing prompts or credentials."""
from alembic import op
import sqlalchemy as s
revision='0006_ai_jobs'
down_revision='0005_intelligence'
branch_labels=None
depends_on=None
def upgrade():
    op.add_column('ai_usage',s.Column('request',s.JSON(),nullable=True))
    op.add_column('ai_usage',s.Column('result',s.JSON(),nullable=True))
def downgrade():
    with op.batch_alter_table('ai_usage') as table:
        table.drop_column('result');table.drop_column('request')
