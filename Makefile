# Run from the repository root. All automated tests use isolated/mocked data.
.PHONY: test test-backend test-frontend test-audits test-leads test-shell test-security check

test: test-backend test-frontend

test-backend:
	@cd backend && .venv/bin/python -m pytest

test-frontend:
	@cd frontend && npm test

# Select the feature being changed during development; these are not completion gates.
test-audits:
	@cd backend && .venv/bin/python -m pytest tests/test_audit_network.py tests/test_audit_runner.py tests/test_audit_manager.py
	@cd frontend && npm test -- src/Audits.test.tsx

test-leads:
	@cd backend && .venv/bin/python -m pytest tests/test_leads.py tests/test_migrations.py
	@cd frontend && npm test -- src/Leads.test.tsx

test-shell:
	@cd backend && .venv/bin/python -m pytest tests/test_health.py
	@cd frontend && npm test -- src/App.test.tsx

# Includes URL input, network/robots/redirect checks, provider budgets and local access controls.
test-security:
	@cd backend && .venv/bin/python -m pytest tests/test_audit_network.py tests/test_audit_runner.py tests/test_audit_manager.py tests/test_health.py tests/test_leads.py::test_reject_invalid_or_nonpublic_url

# Once per completed checkpoint (or after additional changes/failures invalidate the result).
# Browser/provider checks remain separate and explicitly selected; no external calls here.
check: test
	@cd frontend && npm run build
