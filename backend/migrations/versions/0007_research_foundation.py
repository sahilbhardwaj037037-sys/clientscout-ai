"""Frozen additive SQLite research schema; historical tables remain untouched."""
from alembic import op
revision='0007_research_foundation'
down_revision='0006_ai_jobs'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("""
    CREATE TABLE research_plans (
        id INTEGER NOT NULL,
        series_id VARCHAR(36) NOT NULL,
        revision INTEGER NOT NULL,
        previous_id INTEGER,
        fingerprint VARCHAR(64) NOT NULL,
        data JSON NOT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (series_id, revision),
        CHECK (revision >= 1),
        FOREIGN KEY(previous_id) REFERENCES research_plans (id)
    )
    """)
    op.execute("""
    CREATE TABLE research_jobs (
        id INTEGER NOT NULL,
        request_id VARCHAR(36) NOT NULL,
        request_hash VARCHAR(64) NOT NULL,
        plan_id INTEGER NOT NULL,
        status VARCHAR(30) NOT NULL,
        version INTEGER NOT NULL,
        attempts_used INTEGER NOT NULL,
        runtime_reserved_ms INTEGER NOT NULL,
        requests_used INTEGER NOT NULL,
        gemini_attempts_used INTEGER NOT NULL,
        error_code VARCHAR(40),
        next_retry_at DATETIME,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        CHECK (status IN ('queued','running','waiting_for_approval','waiting_for_budget','waiting_for_retry','paused','cancelling','cancelled','interrupted','failed','completed')),
        CHECK (attempts_used >= 0 AND runtime_reserved_ms >= 0 AND requests_used = 0 AND gemini_attempts_used = 0),
        UNIQUE (request_id),
        UNIQUE (plan_id),
        FOREIGN KEY(plan_id) REFERENCES research_plans (id)
    )
    """)
    op.execute('CREATE INDEX ix_research_jobs_status ON research_jobs (status)')
    op.execute("""
    CREATE TABLE research_steps (
        id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        kind VARCHAR(30) NOT NULL,
        idempotency_key VARCHAR(64) NOT NULL,
        status VARCHAR(20) NOT NULL,
        replay_safe BOOLEAN NOT NULL,
        result_ref JSON,
        PRIMARY KEY (id),
        UNIQUE (job_id, position),
        CHECK (status IN ('pending','running','succeeded','cancelled','interrupted','failed','uncertain')),
        CHECK (kind IN ('validate_plan','summarize_plan','external_reserved')),
        FOREIGN KEY(job_id) REFERENCES research_jobs (id),
        UNIQUE (idempotency_key)
    )
    """)
    op.execute('CREATE INDEX ix_research_steps_job_id ON research_steps (job_id)')
    op.execute("""
    CREATE TABLE research_attempts (
        id INTEGER NOT NULL,
        step_id INTEGER NOT NULL,
        number INTEGER NOT NULL,
        owner VARCHAR(36) NOT NULL,
        epoch INTEGER NOT NULL,
        status VARCHAR(20) NOT NULL,
        dispatch_state VARCHAR(20) NOT NULL,
        reserved_ms INTEGER NOT NULL,
        error_code VARCHAR(40),
        started_at DATETIME NOT NULL,
        finished_at DATETIME,
        PRIMARY KEY (id),
        UNIQUE (step_id, number),
        CHECK (status IN ('started','succeeded','failed','cancelled','interrupted','uncertain')),
        CHECK (dispatch_state IN ('reserved','started','finished','uncertain')),
        FOREIGN KEY(step_id) REFERENCES research_steps (id)
    )
    """)
    op.execute('CREATE INDEX ix_research_attempts_step_id ON research_attempts (step_id)')
    op.execute("""
    CREATE TABLE research_approvals (
        id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        step_id INTEGER NOT NULL,
        attempt_id INTEGER,
        reason VARCHAR(40) NOT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(job_id) REFERENCES research_jobs (id),
        UNIQUE (step_id),
        FOREIGN KEY(step_id) REFERENCES research_steps (id),
        FOREIGN KEY(attempt_id) REFERENCES research_attempts (id)
    )
    """)
    op.execute('CREATE INDEX ix_research_approvals_job_id ON research_approvals (job_id)')
    op.execute("""
    CREATE TABLE research_events (
        id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        code VARCHAR(40) NOT NULL,
        step_id INTEGER,
        attempt_id INTEGER,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(job_id) REFERENCES research_jobs (id),
        FOREIGN KEY(step_id) REFERENCES research_steps (id),
        FOREIGN KEY(attempt_id) REFERENCES research_attempts (id)
    )
    """)
    op.execute('CREATE INDEX ix_research_events_job_id ON research_events (job_id)')
    op.execute("""
    CREATE TABLE research_worker_lease (
        id INTEGER NOT NULL,
        owner VARCHAR(36),
        epoch INTEGER NOT NULL,
        expires_at DATETIME,
        PRIMARY KEY (id),
        CHECK (id = 1)
    )
    """)
    op.execute("CREATE TRIGGER research_plan_immutable BEFORE UPDATE ON research_plans BEGIN SELECT RAISE(ABORT, 'Research plan revisions are immutable'); END")
    op.execute("CREATE TRIGGER research_job_plan_immutable BEFORE UPDATE OF plan_id, request_id, request_hash ON research_jobs BEGIN SELECT RAISE(ABORT, 'Research job plan binding is immutable'); END")

def downgrade():
    op.execute('DROP TRIGGER research_job_plan_immutable')
    op.execute('DROP TRIGGER research_plan_immutable')
    for name in ('research_events','research_approvals','research_attempts','research_steps','research_jobs','research_plans','research_worker_lease'):
        op.drop_table(name)
