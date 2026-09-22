.PHONY: help build up down restart logs shell db-shell test clean migrate migration

help:
	@echo "FlexMapping - Available commands:"
	@echo ""
	@echo "  make build          - Build Docker images"
	@echo "  make up             - Start all services"
	@echo "  make down           - Stop all services"
	@echo "  make restart        - Restart all services"
	@echo "  make logs           - Show logs (all services)"
	@echo "  make logs-app       - Show API logs"
	@echo "  make logs-worker    - Show Worker logs"
	@echo "  make shell          - Shell into app container"
	@echo "  make db-shell       - PostgreSQL shell"
	@echo "  make redis-shell    - Redis CLI"
	@echo "  make test           - Run tests"
	@echo "  make clean          - Clean up containers and volumes"
	@echo "  make migrate        - Run database migrations"
	@echo "  make migration      - Create new migration"
	@echo "  make dev-api        - Run API locally (dev mode)"
	@echo "  make dev-worker     - Run Worker locally (dev mode)"

setup:
	bash scripts/setup.sh

build:
	docker compose build

dev-up:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

up:
	docker compose up -d
	@echo "Services started!"
	@echo "API: http://localhost:8000"
	@echo "API Docs: http://localhost:8000/docs"

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f

logs-app:
	docker compose logs -f app

logs-worker:
	docker compose logs -f worker

shell:
	docker compose exec app /bin/bash

db-shell:
	docker compose exec db psql -U flexmap -d flexmap

redis-shell:
	docker compose exec redis redis-cli

test:
	docker compose exec app pytest

clean:
	docker compose down -v
	rm -rf __pycache__
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

migrate:
	docker compose exec app alembic upgrade head

migration:
	@read -p "Migration message: " msg; \
	docker compose exec app alembic revision --autogenerate -m "$$msg"

# Development commands (without Docker)
dev-setup:
	python -m venv venv
	. venv/bin/activate && pip install -r requirements.txt
	cp .env.example .env
	@echo "Edit .env with your settings!"

dev-api:
	python -m app.main

dev-worker:
	python -m app.worker

dev-migrate:
	alembic upgrade head

dev-migration:
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

# Initial setup
init: build up
	@echo "Waiting for database..."
	@sleep 5
	$(MAKE) migrate
	@echo ""
	@echo "Setup complete!"
	@echo "API: http://localhost:8000"
	@echo "API Docs: http://localhost:8000/docs"

# Rebuild the vendored Tailwind stylesheet. Needed after adding a Tailwind
# class that does not already appear somewhere in the templates.
assets:
	npx --yes tailwindcss@3.4.17 -c tools/tailwind.config.js -i tools/tailwind.css -o app/static/vendor/tailwind.min.css --minify

# The command list that CONTRIBUTING.md defines as "checked".
# PYTHON can be overridden: make check PYTHON=.venv/bin/python
PYTHON ?= python3

check:
	$(PYTHON) -m compileall -q app tests tools scripts generate_site.py alembic
	PYTHONPATH=$(CURDIR) $(PYTHON) -m pytest tests/ -q
