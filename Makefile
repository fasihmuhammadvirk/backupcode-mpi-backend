.PHONY: setup dbt-deps migrate dev test

## Full local setup: install dbt packages and run migrations
## (Python deps are handled separately by ./setup.sh / .\setup.ps1)
setup: dbt-deps migrate
	@echo "Setup complete. Run 'make dev' to start the server."

## Install dbt packages (dbt_packages/ is gitignored)
dbt-deps:
	(cd mpi_analytics && uv run python run_dbt.py deps)

## Run database migrations
migrate:
	uv run alembic upgrade head

## Start development server with hot-reload
dev:
	uv run uvicorn mpi_backend.main:app --reload --host 0.0.0.0 --port 8000

## Run tests
test:
	uv run pytest
