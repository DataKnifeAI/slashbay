.PHONY: help install test lint run docker-up docker-down kustomize

help:
	@echo "install     pip install -e .[dev]"
	@echo "test        pytest"
	@echo "lint        ruff check src tests"
	@echo "run         uvicorn slashbay.app:app --reload --port 8080"
	@echo "docker-up   docker compose up --build"
	@echo "docker-down docker compose down"
	@echo "kustomize   render deploy/overlays/prd-apps"

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

kustomize:
	kubectl kustomize deploy/overlays/prd-apps
