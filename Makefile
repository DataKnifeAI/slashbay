.PHONY: help install test lint run docker-up docker-down

help:
	@echo "install     pip install -e .[dev]"
	@echo "test        pytest"
	@echo "lint        ruff check src tests"
	@echo "run         uvicorn slashbay.app:app --reload --port 8080"
	@echo "docker-up   docker compose up --build"
	@echo "docker-down docker compose down"

install:
	python3 -m pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check src tests

run:
	uvicorn slashbay.app:app --reload --host 127.0.0.1 --port 8080

docker-up:
	docker compose up --build

docker-down:
	docker compose down
