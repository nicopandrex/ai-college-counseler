.PHONY: install test test-py test-web lint db-up db-down solver-dev web-dev

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

solver-dev:
	uv run --frozen uvicorn planner_solver.app:app --reload --port 8000

web-dev:
	cd web && npm run dev
