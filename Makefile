.PHONY: dev dev-build dev-logs dev-down prod prod-build prod-logs prod-down deploy backup ssl status health test test-api test-web test-db-up test-db-down

# Development
dev:
	cd infra && docker compose up -d

dev-build:
	cd infra && docker compose build && docker compose up -d

dev-logs:
	cd infra && docker compose logs -f --tail=50

dev-down:
	cd infra && docker compose down

# Production
prod:
	cd infra && docker compose -f docker-compose.prod.yml up -d

prod-build:
	cd infra && docker compose -f docker-compose.prod.yml build && docker compose -f docker-compose.prod.yml up -d

prod-logs:
	cd infra && docker compose -f docker-compose.prod.yml logs -f --tail=50

prod-down:
	cd infra && docker compose -f docker-compose.prod.yml down

# Deploy
deploy:
	bash infra/deploy.sh

# Backup
backup:
	bash infra/backup.sh

# SSL
ssl:
	@read -p "Domain: " domain; sudo bash infra/init-ssl.sh $$domain

# Status
status:
	cd infra && docker compose ps

# Health
health:
	@curl -sf http://localhost:8080/api/health && echo " OK" || echo " FAILED"

# ── Tests ──────────────────────────────────────────────────────────
# Spin up an ephemeral Postgres for backend tests on port 5433.
# Use `make test-db-up` then `make test-api`, or just `make test` to do both.
test-db-up:
	@docker rm -f vre-test-pg 2>/dev/null || true
	docker run -d --name vre-test-pg -p 5433:5432 \
		-e POSTGRES_USER=vre_user -e POSTGRES_PASSWORD=vre_pass -e POSTGRES_DB=vre_test \
		postgres:16-alpine
	@echo "Waiting for Postgres..."
	@until docker exec vre-test-pg pg_isready -U vre_user -d vre_test >/dev/null 2>&1; do sleep 0.5; done
	@echo "✓ test DB ready at postgresql+asyncpg://vre_user:vre_pass@localhost:5433/vre_test"

test-db-down:
	@docker rm -f vre-test-pg 2>/dev/null || true

# Backend tests: requires a venv with requirements.txt + requirements-test.txt installed.
# Expects Postgres at $$TEST_DATABASE_URL (default: localhost:5433 via `make test-db-up`).
test-api:
	@cd services/api && TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql+asyncpg://vre_user:vre_pass@localhost:5433/vre_test} \
		python -m pytest -q

# Frontend tests: requires `npm install` in apps/web/ first.
test-web:
	@cd apps/web && npm test

# Run the full suite (assumes test-db-up has been called).
test: test-api test-web
