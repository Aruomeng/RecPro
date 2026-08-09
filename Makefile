PYTHON ?= python3.11
NPM ?= npm
COMPOSE ?= docker compose
COMPOSE_ENV_FILE ?= .env.compose
COMPOSE_EXAMPLE_ENV_FILE ?= .env.compose.example
RUN_ID ?=
BUILD_RUN_ID ?=
G2_RUN_ID ?=
G2_USER_ID ?=
G2_AS_OF ?=
G3_RUN_ID ?=
G3_USER_ID ?= 1001
G3_INPUT_TEXT ?= 多智能体推荐系统论文与图书
G3_AS_OF ?=
G4_RUN_ID ?=
G4_AGENT_RUN_ID ?=
G4_PORT_RUN_ID ?=
G4_COMPOSITION_RUN_ID ?=
G5_RUN_ID ?=

.PHONY: \
	bootstrap bootstrap-check \
	safety-check architecture-check docs-check contracts-check \
	test-g0 test-g1-python frontend-test frontend-build \
	test-g2 test-g3 test-g4 test-g5 g2-tools-install g2-dataset-report plan-g2-indexes verify-g0 verify-g1-local verify-g1-runtime verify-g1 verify-g2-local verify-g3-local verify-g4-local verify-g5-local \
	migrate-g2 migrate-g5 seed-g2 replay-g2 verify-g2-runtime migrate-g3 migrate-g3-transition migrate-g3-clarification migrate-g4-agent-logs g3-demo verify-g3-runtime verify-g3-api-runtime verify-g3-clarification-runtime verify-g4-orchestrator verify-g4-agent-logs verify-g4-real-ports verify-g4-composition verify-g5-runtime compose-config \
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

test-g2:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/g2 -t tests -p 'test_*.py'

test-g3:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/g3 -t tests -p 'test_*.py'

test-g4:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/g4 -t tests -p 'test_*.py'

test-g5:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/g5 -t tests -p 'test_*.py'

g2-tools-install:
	$(PYTHON) -m pip install --require-hashes -r backend/requirements-g2-tools.lock

g2-dataset-report:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_g2_dataset_report

plan-g2-indexes:
	@test -n "$(G2_RUN_ID)" || { echo "G2_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.plan_g2_indexes --run-id "$(G2_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --apply

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

verify-g2-local: verify-g0 test-g1-python test-g2

verify-g3-local: verify-g2-local test-g3

verify-g4-local: verify-g3-local test-g4

verify-g5-local: verify-g4-local test-g5

verify-g5-runtime:
	@test -n "$(G5_RUN_ID)" || { echo "G5_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g5_feedback_runtime --run-id "$(G5_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g4-orchestrator:
	@test -n "$(G4_RUN_ID)" || { echo "G4_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_orchestrator --run-id "$(G4_RUN_ID)"

migrate-g4-agent-logs:
	@test -n "$(G4_AGENT_RUN_ID)" || { echo "G4_AGENT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.migrate_g4_agent_logs --run-id "$(G4_AGENT_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --apply

verify-g4-agent-logs:
	@test -n "$(G4_AGENT_RUN_ID)" || { echo "G4_AGENT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_agent_logs_runtime --run-id "$(G4_AGENT_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g4-real-ports:
	@test -n "$(G4_PORT_RUN_ID)" || { echo "G4_PORT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_real_ports_runtime --run-id "$(G4_PORT_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g4-composition:
	@test -n "$(G4_COMPOSITION_RUN_ID)" || { echo "G4_COMPOSITION_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_composition_runtime --run-id "$(G4_COMPOSITION_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

migrate-g2:
	@test -n "$(G2_RUN_ID)" || { echo "G2_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.migrate_g2 --run-id "$(G2_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --apply

migrate-g5:
	@test -n "$(G5_RUN_ID)" || { echo "G5_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.migrate_g5_feedback --run-id "$(G5_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --apply

seed-g2:
	@test -n "$(G2_RUN_ID)" || { echo "G2_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.seed_g2 --run-id "$(G2_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --apply

replay-g2:
	@test -n "$(G2_RUN_ID)" || { echo "G2_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(G2_USER_ID)" || { echo "G2_USER_ID is required"; exit 2; }
	@test -n "$(G2_AS_OF)" || { echo "G2_AS_OF is required and must be an ISO-8601 UTC time"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.replay_g2_profile --run-id "$(G2_RUN_ID)" --user-id "$(G2_USER_ID)" --as-of "$(G2_AS_OF)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g2-runtime:
	@test -n "$(G2_RUN_ID)" || { echo "G2_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g2_runtime --run-id "$(G2_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

migrate-g3:
	@test -n "$(G3_RUN_ID)" || { echo "G3_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.migrate_g3 --run-id "$(G3_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --apply

migrate-g3-transition:
	@test -n "$(G3_RUN_ID)" || { echo "G3_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.migrate_g3_transition --run-id "$(G3_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --apply

migrate-g3-clarification:
	@test -n "$(G3_RUN_ID)" || { echo "G3_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.migrate_g3_clarification --run-id "$(G3_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --apply

g3-demo:
	@test -n "$(G3_RUN_ID)" || { echo "G3_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(G3_USER_ID)" || { echo "G3_USER_ID is required"; exit 2; }
	@test -n "$(G3_INPUT_TEXT)" || { echo "G3_INPUT_TEXT is required"; exit 2; }
	@test -n "$(G3_AS_OF)" || { echo "G3_AS_OF is required and must be an ISO-8601 UTC time"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.run_g3_demo --run-id "$(G3_RUN_ID)" --user-id "$(G3_USER_ID)" --input-text "$(G3_INPUT_TEXT)" --evaluation-at "$(G3_AS_OF)" --env-file "$(COMPOSE_ENV_FILE)" --apply

verify-g3-runtime:
	@test -n "$(G3_RUN_ID)" || { echo "G3_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g3_runtime --run-id "$(G3_RUN_ID)" --user-id "$(G3_USER_ID)" --input-text "$(G3_INPUT_TEXT)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g3-api-runtime:
	@test -n "$(G3_RUN_ID)" || { echo "G3_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g3_api_runtime --run-id "$(G3_RUN_ID)" --user-id "$(G3_USER_ID)" --input-text "$(G3_INPUT_TEXT)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g3-clarification-runtime:
	@test -n "$(G3_RUN_ID)" || { echo "G3_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g3_clarification_runtime --run-id "$(G3_RUN_ID)" --user-id "$(G3_USER_ID)" --env-file "$(COMPOSE_ENV_FILE)"

compose-config:
	RECPRO_MYSQL_PASSWORD=validation-runtime-001 \
	RECPRO_MYSQL_MIGRATION_PASSWORD=validation-migration-004 \
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
