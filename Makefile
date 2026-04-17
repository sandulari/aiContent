.PHONY: dev dev-build dev-logs dev-down prod prod-build prod-logs prod-down deploy backup ssl status health

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
