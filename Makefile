PYTHON ?= python3.11
NPM ?= npm
COMPOSE ?= docker compose
COMPOSE_ENV_FILE ?= .env.compose
COMPOSE_EXAMPLE_ENV_FILE ?= .env.compose.example
RUN_ID ?=
BUILD_RUN_ID ?=

.PHONY: \
	bootstrap bootstrap-check \
	safety-check architecture-check docs-check contracts-check \
	test-g0 test-g1-python frontend-test frontend-build \
	verify-g0 verify-g1-local verify-g1-runtime verify-g1 compose-config \
	start stop status infra-start infra-stop backend frontend worker git-status

bootstrap-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/bootstrap.py

bootstrap:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/bootstrap.py --create-config

safety-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/safety_scan.py --root .

architecture-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/architecture_guard.py --root .

docs-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.validate_docs --root .

contracts-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.validate_contracts --root .

test-g0:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/contracts -p 'test_*.py'
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/architecture -p 'test_*.py'
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/safety -p 'test_*.py'

test-g1-python:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/g1 -t tests -p 'test_*.py'

frontend-test:
	$(NPM) --prefix frontend run test

frontend-build:
	@test -n "$(BUILD_RUN_ID)" || { echo "BUILD_RUN_ID is required and must name a new append-only frontend build"; exit 2; }
	RECPRO_BUILD_RUN_ID="$(BUILD_RUN_ID)" $(NPM) --prefix frontend run build

verify-g0: safety-check architecture-check docs-check contracts-check test-g0

verify-g1-local: verify-g0 test-g1-python frontend-test frontend-build

verify-g1-runtime:
	@test -n "$(RUN_ID)" || { echo "RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g1_runtime --run-id "$(RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g1: verify-g1-local verify-g1-runtime

compose-config:
	RECPRO_MYSQL_PASSWORD=validation-runtime-001 \
	RECPRO_MYSQL_ROOT_PASSWORD=validation-bootstrap-002 \
	RECPRO_NEO4J_PASSWORD=validation-graph-003 \
	$(COMPOSE) --env-file "$(COMPOSE_EXAMPLE_ENV_FILE)" config --quiet

start:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/validate_runtime_env.py --mode compose --env-file "$(COMPOSE_ENV_FILE)"
	$(COMPOSE) --env-file "$(COMPOSE_ENV_FILE)" up --build --detach

stop:
	$(COMPOSE) --env-file "$(COMPOSE_ENV_FILE)" stop

status:
	$(COMPOSE) --env-file "$(COMPOSE_ENV_FILE)" ps

infra-start:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/validate_runtime_env.py --mode compose --env-file "$(COMPOSE_ENV_FILE)"
	$(COMPOSE) --env-file "$(COMPOSE_ENV_FILE)" up --detach mysql neo4j

infra-stop:
	$(COMPOSE) --env-file "$(COMPOSE_ENV_FILE)" stop mysql neo4j

backend:
	@test -f .env.host || { echo ".env.host is missing; run make bootstrap after installing prerequisites"; exit 2; }
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/validate_runtime_env.py --mode host --env-file .env.host
	@set -a; . ./.env.host; set +a; exec $(PYTHON) -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$${RECPRO_BACKEND_PORT:-8000}" --reload

frontend:
	$(NPM) --prefix frontend run dev

worker:
	@test -f .env.host || { echo ".env.host is missing; run make bootstrap after installing prerequisites"; exit 2; }
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/validate_runtime_env.py --mode host --env-file .env.host
	@set -a; . ./.env.host; set +a; exec $(PYTHON) -m backend.app.worker

git-status:
	git status --short --branch
