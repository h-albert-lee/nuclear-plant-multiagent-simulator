.PHONY: install dev fmt lint typecheck test build up down logs clean smoke

PY := python
PIP := pip

install:
	$(PIP) install -e ".[dev]"

dev: install
	@echo "Dev environment ready."

fmt:
	ruff format src llm_proxy tests

lint:
	ruff check src llm_proxy tests

typecheck:
	mypy src llm_proxy

test:
	pytest -v

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f simulator

clean:
	rm -rf runs/*/
	rm -rf .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

smoke:
	$(PY) -m src.main --config configs/config.yaml --scenario scenarios/normal_baseline.yaml --max-ticks 50 --mock-llm

smoke-sbo:
	$(PY) -m src.main --config configs/config.yaml --scenario scenarios/sbo_v1.yaml --max-ticks 200 --mock-llm

smoke-loca:
	$(PY) -m src.main --config configs/config.yaml --scenario scenarios/loca_small.yaml --max-ticks 250 --mock-llm

smoke-sgtr:
	$(PY) -m src.main --config configs/config.yaml --scenario scenarios/sgtr_v1.yaml --max-ticks 250 --mock-llm
