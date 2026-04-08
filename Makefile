# =========================================================
# Makefile
# =========================================================
#
# Provides tasks for:
# - Setting up virtual environments
# - Installing dependencies
# - Running tests and type checks
# - Formatting and linting code
#
# Usage examples:
# - make install    # Setup environment + install dependencies
# - make test       # Run unit and integration tests
# - make format     # Format code
# - make check      # Run lint, typecheck, and tests

# =========================================================
# Variables
# =========================================================

VENV          := .venv
VENV_BIN      := $(VENV)/bin
PYTHON        := $(VENV_BIN)/python

PACKAGE_NAME  := pdf2markdown
SRC           := src
TESTS         := tests

.DEFAULT_GOAL := help

.PHONY: help install run test coverage lint format typecheck check clean notebook-kernel

help: ## Show all available commands
	@grep -hE '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | \
		sort | \
		awk 'BEGIN {FS=":.*##"} {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

$(VENV)/.installed: pyproject.toml uv.lock
	uv sync --extra dev
	@touch $@

install: $(VENV)/.installed ## Install project (skipped if up to date)

run: $(VENV)/.installed ## Start the Flask dev server on port 5000
	uv run python src/pdf2markdown/app.py

notebook-kernel: $(VENV)/.installed ## Register venv as Jupyter kernel
	uv run python -m ipykernel install --user --name=$(PACKAGE_NAME) \
	    --display-name "Python $$(uv run python -c 'import sys; print(f\"{sys.version_info.major}.{sys.version_info.minor}\")') ($(PACKAGE_NAME))"

# =========================================================
# Testing
# =========================================================

test: $(VENV)/.installed ## Run pytest
	@echo "Running tests..."
	uv run pytest $(TESTS)

coverage: $(VENV)/.installed ## Run tests with coverage report
	uv run pytest --cov $(TESTS)

# =========================================================
# Code Quality
# =========================================================

lint: $(VENV)/.installed ## Run Ruff for linting
	uv run ruff check $(SRC) $(TESTS)

format: $(VENV)/.installed ## Auto-fix lint + format
	uv run ruff check --fix $(SRC) $(TESTS)
	uv run ruff format $(SRC) $(TESTS)

typecheck: $(VENV)/.installed ## Run mypy static type checking
	uv run mypy $(SRC)

check: lint typecheck test ## Run lint + typecheck + tests

# =========================================================
# Cleaning
# =========================================================

clean: ## Remove caches and virtual environment
	@echo "Cleaning up..."
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name '__pycache__' -exec rm -rf {} +
