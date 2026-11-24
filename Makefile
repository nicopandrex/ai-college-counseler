.PHONY: install test test-py test-web lint db-up db-down api-dev web-dev dev

install:
	uv sync --frozen
	cd web && npm ci

test: test-py test-web

test-py:
	uv run --frozen pytest -q

test-web:
	cd web && npm test --silent

lint:
	uv run --frozen ruff check .
	uv run --frozen ruff format --check .
	cd web && npm run --silent typecheck

db-up:
	docker compose up -d db

db-down:
	docker compose down

api-dev:
	uv run --frozen planner-api

web-dev:
	cd web && npm run dev

# the web app on http://localhost:3000 (API on :8000); needs the LLM_* env (see README)
dev:
	$(MAKE) -j2 api-dev web-dev
