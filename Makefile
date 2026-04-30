.PHONY: lint format typecheck test

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

typecheck:
	uv run mypy src/

test:
	uv run pytest tests/ -v

test-unit:
	uv run pytest tests/ -v -m unit
