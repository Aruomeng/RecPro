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
G5_HTTP_RUN_ID ?=
G5_WORKER_RUN_ID ?=
G5_AUDIT_RUN_ID ?=
G6_RUN_ID ?=
FORMAL_AUTH_RUN_ID ?=
FREEZE_RUN_ID ?=
EVAL_INPUT_RUN_ID ?=
BOOK_INTAKE_RUN_ID ?=
DATA_PLANE_RUN_ID ?=
BOOK_GRAPH_PLAN_RUN_ID ?=
BOOK_GRAPH_IMPORT_RUN_ID ?=
BOOK_GRAPH_GRAPH_VERSION ?=
BOOK_GRAPH_LICENSE_STATUS ?= PENDING_USER_CONFIRMATION
BOOK_GRAPH_PLAN_DIR ?=
BOOK_GRAPH_SECRET_ENV_FILE ?= .env.user-secrets
MYSQL_BOOK_PLAN_RUN_ID ?=
MYSQL_BOOK_GRAPH_PLAN_DIR ?=
MYSQL_BOOK_AVAILABLE_FROM ?= 2026-08-10T00:00:00Z
MYSQL_BOOK_PLAN_DIR ?=
MYSQL_BOOK_IMPORT_RUN_ID ?=
MYSQL_BOOK_PREFLIGHT_RUN_ID ?=
MYSQL_BOOK_MYSQL_ENV_FILE ?= .env.compose
VECTOR_INDEX_PLAN_RUN_ID ?=
VECTOR_INDEX_VERIFY_RUN_ID ?=
VECTOR_INDEX_MYSQL_PLAN_DIR ?=
VECTOR_INDEX_PLAN_DIR ?=
CHROMA_COLLECTION_PLAN_RUN_ID ?=
CHROMA_COLLECTION_VECTOR_PLAN ?=
CHROMA_COLLECTION_VERIFY_RUN_ID ?=
CHROMA_COLLECTION_PLAN ?=
CHROMA_IMPORT_RUN_ID ?=
CHROMA_IMPORT_VERIFY_RUN_ID ?=
CHROMA_IMPORT_IDEMPOTENCY_RUN_ID ?=
CHROMA_IMPORT_PLAN ?=
CHROMA_IMPORT_CHROMA_PATH ?= data/chroma
CHROMA_OPERATOR_PYTHON ?= .venv-chroma-g6-20260811/bin/python

.PHONY: \
	bootstrap bootstrap-check \
	safety-check architecture-check docs-check contracts-check \
	test-g0 test-g1-python frontend-test frontend-build \
	test-g2 test-g3 test-g4 test-g5 test-g6 test-g9 g2-tools-install g2-dataset-report plan-g2-indexes verify-g0 verify-g1-local verify-g1-runtime verify-g1 verify-g2-local verify-g3-local verify-g4-local verify-g5-local \
	migrate-g2 migrate-g5 migrate-g5-audit seed-g2 replay-g2 verify-g2-runtime migrate-g3 migrate-g3-transition migrate-g3-clarification migrate-g4-agent-logs g3-demo verify-g3-runtime verify-g3-api-runtime verify-g3-clarification-runtime verify-g4-orchestrator verify-g4-agent-logs verify-g4-real-ports verify-g4-composition verify-g5-runtime compose-config \
	verify-g5-http-runtime verify-g5-worker-prepare verify-g5-worker-resume verify-g5-audit-replay-runtime \
	verify-formal-auth-runtime \
	verify-experiment-freeze verify-evaluation-freeze-inputs verify-book-intake verify-data-plane-runtime \
	build-book-graph-plan verify-book-graph-plan import-book-graph \
	build-mysql-book-plan verify-mysql-book-plan preflight-mysql-book-catalog import-mysql-book-catalog \
	build-vector-index-plan verify-vector-index-plan build-chroma-collection-plan verify-chroma-collection-plan \
	preflight-chroma-import import-chroma-vectors import-chroma-vectors-idempotency verify-chroma-import \
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

test-g6:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/g6 -t tests -p 'test_*.py'

test-g9:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/g9 -t tests -p 'test_*.py'

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

verify-g5-http-runtime:
	@test -n "$(G5_HTTP_RUN_ID)" || { echo "G5_HTTP_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g5_http_runtime --run-id "$(G5_HTTP_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g5-worker-prepare:
	@test -n "$(G5_WORKER_RUN_ID)" || { echo "G5_WORKER_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g5_worker_recovery_runtime --run-id "$(G5_WORKER_RUN_ID)" --phase prepare --env-file "$(COMPOSE_ENV_FILE)"

verify-g5-worker-resume:
	@test -n "$(G5_WORKER_RUN_ID)" || { echo "G5_WORKER_RUN_ID is required and must identify the prepared evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g5_worker_recovery_runtime --run-id "$(G5_WORKER_RUN_ID)" --phase resume --env-file "$(COMPOSE_ENV_FILE)"

verify-g5-audit-replay-runtime:
	@test -n "$(G5_AUDIT_RUN_ID)" || { echo "G5_AUDIT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g5_audit_replay_runtime --run-id "$(G5_AUDIT_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-formal-auth-runtime:
	@test -n "$(FORMAL_AUTH_RUN_ID)" || { echo "FORMAL_AUTH_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_formal_auth_runtime --run-id "$(FORMAL_AUTH_RUN_ID)"

verify-experiment-freeze:
	@test -n "$(FREEZE_RUN_ID)" || { echo "FREEZE_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_experiment_freeze --run-id "$(FREEZE_RUN_ID)"

verify-evaluation-freeze-inputs:
	@test -n "$(EVAL_INPUT_RUN_ID)" || { echo "EVAL_INPUT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_evaluation_freeze_inputs --run-id "$(EVAL_INPUT_RUN_ID)"

verify-book-intake:
	@test -n "$(BOOK_INTAKE_RUN_ID)" || { echo "BOOK_INTAKE_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.inspect_book_intake --run-id "$(BOOK_INTAKE_RUN_ID)"

verify-data-plane-runtime:
	@test -n "$(DATA_PLANE_RUN_ID)" || { echo "DATA_PLANE_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_data_plane_runtime --run-id "$(DATA_PLANE_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

build-book-graph-plan:
	@test -n "$(BOOK_GRAPH_PLAN_RUN_ID)" || { echo "BOOK_GRAPH_PLAN_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(BOOK_GRAPH_GRAPH_VERSION)" || { echo "BOOK_GRAPH_GRAPH_VERSION is required and must identify a new graph version"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_book_graph_plan --run-id "$(BOOK_GRAPH_PLAN_RUN_ID)" --graph-version "$(BOOK_GRAPH_GRAPH_VERSION)" --license-status "$(BOOK_GRAPH_LICENSE_STATUS)"

verify-book-graph-plan:
	@test -n "$(BOOK_GRAPH_IMPORT_RUN_ID)" || { echo "BOOK_GRAPH_IMPORT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(BOOK_GRAPH_PLAN_DIR)" || { echo "BOOK_GRAPH_PLAN_DIR is required and must point to a reviewed plan directory"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.import_book_graph --run-id "$(BOOK_GRAPH_IMPORT_RUN_ID)" --plan-dir "$(BOOK_GRAPH_PLAN_DIR)" --env-file "$(BOOK_GRAPH_SECRET_ENV_FILE)" --license-status "$(BOOK_GRAPH_LICENSE_STATUS)"

import-book-graph:
	@test -n "$(BOOK_GRAPH_IMPORT_RUN_ID)" || { echo "BOOK_GRAPH_IMPORT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(BOOK_GRAPH_PLAN_DIR)" || { echo "BOOK_GRAPH_PLAN_DIR is required and must point to a reviewed plan directory"; exit 2; }
	@test "$(BOOK_GRAPH_LICENSE_STATUS)" != "PENDING_USER_CONFIRMATION" || { echo "BOOK_GRAPH_LICENSE_STATUS must be explicitly confirmed before import"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.import_book_graph --run-id "$(BOOK_GRAPH_IMPORT_RUN_ID)" --plan-dir "$(BOOK_GRAPH_PLAN_DIR)" --env-file "$(BOOK_GRAPH_SECRET_ENV_FILE)" --license-status "$(BOOK_GRAPH_LICENSE_STATUS)" --apply

build-mysql-book-plan:
	@test -n "$(MYSQL_BOOK_PLAN_RUN_ID)" || { echo "MYSQL_BOOK_PLAN_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(MYSQL_BOOK_GRAPH_PLAN_DIR)" || { echo "MYSQL_BOOK_GRAPH_PLAN_DIR is required and must point to a reviewed graph plan directory"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_mysql_book_plan --run-id "$(MYSQL_BOOK_PLAN_RUN_ID)" --graph-plan-dir "$(MYSQL_BOOK_GRAPH_PLAN_DIR)" --available-from "$(MYSQL_BOOK_AVAILABLE_FROM)"

verify-mysql-book-plan:
	@test -n "$(MYSQL_BOOK_IMPORT_RUN_ID)" || { echo "MYSQL_BOOK_IMPORT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(MYSQL_BOOK_PLAN_DIR)" || { echo "MYSQL_BOOK_PLAN_DIR is required and must point to a reviewed MySQL plan directory"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.import_mysql_book_catalog --run-id "$(MYSQL_BOOK_IMPORT_RUN_ID)" --plan-dir "$(MYSQL_BOOK_PLAN_DIR)" --env-file "$(MYSQL_BOOK_MYSQL_ENV_FILE)"

preflight-mysql-book-catalog:
	@test -n "$(MYSQL_BOOK_PREFLIGHT_RUN_ID)" || { echo "MYSQL_BOOK_PREFLIGHT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(MYSQL_BOOK_PLAN_DIR)" || { echo "MYSQL_BOOK_PLAN_DIR is required and must point to a reviewed MySQL plan directory"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.import_mysql_book_catalog --run-id "$(MYSQL_BOOK_PREFLIGHT_RUN_ID)" --plan-dir "$(MYSQL_BOOK_PLAN_DIR)" --env-file "$(MYSQL_BOOK_MYSQL_ENV_FILE)" --preflight-db

import-mysql-book-catalog:
	@test -n "$(MYSQL_BOOK_IMPORT_RUN_ID)" || { echo "MYSQL_BOOK_IMPORT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(MYSQL_BOOK_PLAN_DIR)" || { echo "MYSQL_BOOK_PLAN_DIR is required and must point to a reviewed MySQL plan directory"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.import_mysql_book_catalog --run-id "$(MYSQL_BOOK_IMPORT_RUN_ID)" --plan-dir "$(MYSQL_BOOK_PLAN_DIR)" --env-file "$(MYSQL_BOOK_MYSQL_ENV_FILE)" --apply --confirm-mysql-write

build-vector-index-plan:
	@test -n "$(VECTOR_INDEX_PLAN_RUN_ID)" || { echo "VECTOR_INDEX_PLAN_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(VECTOR_INDEX_MYSQL_PLAN_DIR)" || { echo "VECTOR_INDEX_MYSQL_PLAN_DIR is required and must point to a reviewed MySQL plan directory"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_vector_index_plan --run-id "$(VECTOR_INDEX_PLAN_RUN_ID)" --mysql-plan-dir "$(VECTOR_INDEX_MYSQL_PLAN_DIR)"

verify-vector-index-plan:
	@test -n "$(VECTOR_INDEX_PLAN_DIR)" || { echo "VECTOR_INDEX_PLAN_DIR is required and must point to a reviewed vector plan JSON"; exit 2; }
	@test -n "$(VECTOR_INDEX_VERIFY_RUN_ID)" || { echo "VECTOR_INDEX_VERIFY_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_vector_index_plan --run-id "$(VECTOR_INDEX_VERIFY_RUN_ID)" --plan "$(VECTOR_INDEX_PLAN_DIR)"

build-chroma-collection-plan:
	@test -n "$(CHROMA_COLLECTION_PLAN_RUN_ID)" || { echo "CHROMA_COLLECTION_PLAN_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(CHROMA_COLLECTION_VECTOR_PLAN)" || { echo "CHROMA_COLLECTION_VECTOR_PLAN is required and must point to a reviewed vector plan JSON"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_chroma_collection_plan --run-id "$(CHROMA_COLLECTION_PLAN_RUN_ID)" --vector-plan "$(CHROMA_COLLECTION_VECTOR_PLAN)"

verify-chroma-collection-plan:
	@test -n "$(CHROMA_COLLECTION_PLAN)" || { echo "CHROMA_COLLECTION_PLAN is required and must point to a reviewed Chroma collection plan JSON"; exit 2; }
	@test -n "$(CHROMA_COLLECTION_VERIFY_RUN_ID)" || { echo "CHROMA_COLLECTION_VERIFY_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_chroma_collection_plan --run-id "$(CHROMA_COLLECTION_VERIFY_RUN_ID)" --plan "$(CHROMA_COLLECTION_PLAN)"

preflight-chroma-import:
	@test -n "$(CHROMA_IMPORT_RUN_ID)" || { echo "CHROMA_IMPORT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(CHROMA_IMPORT_PLAN)" || { echo "CHROMA_IMPORT_PLAN is required and must point to a reviewed Chroma collection plan JSON"; exit 2; }
	@test -x "$(CHROMA_OPERATOR_PYTHON)" || { echo "CHROMA_OPERATOR_PYTHON is missing; install backend/requirements-g6-chroma.lock in the isolated operator venv"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 "$(CHROMA_OPERATOR_PYTHON)" -m scripts.import_chroma_vectors --run-id "$(CHROMA_IMPORT_RUN_ID)" --collection-plan "$(CHROMA_IMPORT_PLAN)" --chroma-path "$(CHROMA_IMPORT_CHROMA_PATH)"

import-chroma-vectors:
	@test -n "$(CHROMA_IMPORT_RUN_ID)" || { echo "CHROMA_IMPORT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(CHROMA_IMPORT_PLAN)" || { echo "CHROMA_IMPORT_PLAN is required and must point to a reviewed Chroma collection plan JSON"; exit 2; }
	@test -x "$(CHROMA_OPERATOR_PYTHON)" || { echo "CHROMA_OPERATOR_PYTHON is missing; install backend/requirements-g6-chroma.lock in the isolated operator venv"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 "$(CHROMA_OPERATOR_PYTHON)" -m scripts.import_chroma_vectors --run-id "$(CHROMA_IMPORT_RUN_ID)" --collection-plan "$(CHROMA_IMPORT_PLAN)" --chroma-path "$(CHROMA_IMPORT_CHROMA_PATH)" --apply --confirm-chroma-write

import-chroma-vectors-idempotency:
	@test -n "$(CHROMA_IMPORT_IDEMPOTENCY_RUN_ID)" || { echo "CHROMA_IMPORT_IDEMPOTENCY_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(CHROMA_IMPORT_PLAN)" || { echo "CHROMA_IMPORT_PLAN is required and must point to a reviewed Chroma collection plan JSON"; exit 2; }
	@test -x "$(CHROMA_OPERATOR_PYTHON)" || { echo "CHROMA_OPERATOR_PYTHON is missing; install backend/requirements-g6-chroma.lock in the isolated operator venv"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 "$(CHROMA_OPERATOR_PYTHON)" -m scripts.import_chroma_vectors --run-id "$(CHROMA_IMPORT_IDEMPOTENCY_RUN_ID)" --collection-plan "$(CHROMA_IMPORT_PLAN)" --chroma-path "$(CHROMA_IMPORT_CHROMA_PATH)" --apply --confirm-chroma-write --allow-existing-collection

verify-chroma-import:
	@test -n "$(CHROMA_IMPORT_VERIFY_RUN_ID)" || { echo "CHROMA_IMPORT_VERIFY_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test -n "$(CHROMA_IMPORT_PLAN)" || { echo "CHROMA_IMPORT_PLAN is required and must point to a reviewed Chroma collection plan JSON"; exit 2; }
	@test -x "$(CHROMA_OPERATOR_PYTHON)" || { echo "CHROMA_OPERATOR_PYTHON is missing; install backend/requirements-g6-chroma.lock in the isolated operator venv"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 "$(CHROMA_OPERATOR_PYTHON)" -m scripts.verify_chroma_import --run-id "$(CHROMA_IMPORT_VERIFY_RUN_ID)" --collection-plan "$(CHROMA_IMPORT_PLAN)" --chroma-path "$(CHROMA_IMPORT_CHROMA_PATH)"

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

migrate-g5-audit:
	@test -n "$(G5_AUDIT_RUN_ID)" || { echo "G5_AUDIT_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.migrate_g5_state_transition --run-id "$(G5_AUDIT_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --apply

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
