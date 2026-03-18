.PHONY: help lint format test test-cov build clean dev check install

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

lint: ## Run ruff linter
	ruff check smolclaw/ tests/

format: ## Format code with ruff
	ruff format smolclaw/ tests/

format-check: ## Check code formatting without changes
	ruff format --check smolclaw/ tests/

test: ## Run tests with coverage
	pytest --tb=short -q

test-cov: ## Run tests with full coverage report
	pytest --cov=smolclaw --cov-report=term-missing --cov-report=html

build: ## Build sdist and wheel
	python -m build

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info htmlcov/ .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

dev: ## Install in dev mode with all extras
	pip install -e ".[dev,all]"

check: lint format-check test ## Run all checks (lint + format + test)

install: ## Install from source
	pip install -e .
