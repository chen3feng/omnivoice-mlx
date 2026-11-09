PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: setup download download-mirror run test lint format check clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install -U pip
	$(BIN)/python -m pip install -e ".[mlx,dev]"

download:
	$(BIN)/python scripts/download_models.py --model all

download-mirror:
	$(BIN)/python scripts/download_models.py --model all --mirror

run:
	$(BIN)/python -m omnivoice

test:
	$(BIN)/python -m pytest

lint:
	$(BIN)/ruff check .

format:
	$(BIN)/ruff format .

check:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/python -m pytest

clean:
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
