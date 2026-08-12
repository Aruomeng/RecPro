PYTHON ?= python3.11
NPM ?= npm
# Prefer a working PATH Docker CLI, but keep a read-only fallback for Docker
# Desktop installations whose macOS application bundle is outside the default
# /Applications path.  This does not start, stop, or mutate any container.
DOCKER_CLI ?= $(shell \
	if command -v docker >/dev/null 2>&1 && docker version >/dev/null 2>&1; then \
		printf '%s' docker; \
	elif [ -x "/Applications/Docker.app/Contents/Resources/bin/docker" ]; then \
		printf '%s' "/Applications/Docker.app/Contents/Resources/bin/docker"; \
	elif [ -x "/Applications/编程/Docker.app/Contents/Resources/bin/docker" ]; then \
		printf '%s' "/Applications/编程/Docker.app/Contents/Resources/bin/docker"; \
	else \
		printf '%s' docker; \
	fi)
COMPOSE ?= $(DOCKER_CLI) compose
COMPOSE_ENV_FILE ?= .env.compose
COMPOSE_EXAMPLE_ENV_FILE ?= .env.compose.example
DEMO_BACKEND_ENV_FILE ?= .env.host
DEMO_BACKEND_PORT ?= 8000
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
G4_READONLY_FUSION_RUN_ID ?=
G4_READONLY_FUSION_DEADLINE_SECONDS ?= 180
G4_HTTP_READONLY_HOST_RUN_ID ?=
G4_HTTP_READONLY_HOST_CONFIRM ?=
G4_PROJECTION_PLAN_RUN_ID ?=
G4_PROJECTION_MYSQL_BASELINE ?=
G4_PROJECTION_G4_BASELINE ?=
G4_PROJECTION_USER_ID ?= 1001
G4_PROJECTION_INPUT_TEXT ?= 多智能体系统与智慧图书馆
G4_PROJECTION_LIMIT ?= 8
G4_PROJECTION_REQUEST_ID ?=
G4_PROJECTION_SESSION_ID ?=
G4_PROJECTION_APPLY_RUN_ID ?=
G4_PROJECTION_PLAN ?=
G4_PROJECTION_PLAN_ID ?=
G4_PROJECTION_PLAN_HASH ?=
G4_PROJECTION_REQUEST_RUN_ID ?=
G4_PROJECTION_RECONCILE_RUN_ID ?=
G4_PROJECTION_RECONCILE_APPLY_EVIDENCE ?=
G4_CLARIFICATION_READONLY_RUN_ID ?=
G4_CLARIFICATION_PLAN_RUN_ID ?=
G4_CLARIFICATION_PLAN_EVIDENCE ?=
G4_CLARIFICATION_APPLY_RUN_ID ?=
G4_CLARIFICATION_PLAN ?=
G4_CLARIFICATION_PLAN_ID ?=
G4_CLARIFICATION_PLAN_HASH ?=
G4_CLARIFICATION_REQUEST_RUN_ID ?=
G5_RUN_ID ?=
G5_HTTP_RUN_ID ?=
G5_WORKER_RUN_ID ?=
G5_AUDIT_RUN_ID ?=
G5_FEEDBACK_HTTP_READONLY_RUN_ID ?=
G5_FEEDBACK_HTTP_READONLY_ENV_FILE ?= .env.compose
G5_FEEDBACK_HTTP_READONLY_SECRETS_FILE ?= .env.user-secrets
G5_FEEDBACK_PLAN_RUN_ID ?=
G5_FEEDBACK_PLAN_BASELINE ?=
G5_FEEDBACK_PLAN_TASK_ID ?= b476b901-b78e-5c3e-afd9-6fc880f20623
G5_FEEDBACK_PLAN_RECORD_ID ?= 24
G5_FEEDBACK_PLAN_ITEM_ID ?= 128
G5_FEEDBACK_PLAN_RESOURCE_ID ?= 6452
G5_FEEDBACK_PLAN_USER_ID ?= 1001
G5_FEEDBACK_APPLY_RUN_ID ?=
G5_FEEDBACK_APPLY_PLAN ?=
G5_FEEDBACK_APPLY_PLAN_ID ?=
G5_FEEDBACK_APPLY_PLAN_HASH ?=
G5_FEEDBACK_APPLY_BASELINE ?=
G5_WORKER_WIRING_RUN_ID ?=
G5_WORKER_READONLY_RUN_ID ?=
G6_RUN_ID ?=
G6_READONLY_RUN_ID ?=
G6_READONLY_MYSQL_ENV_FILE ?= .env.compose
G6_READONLY_SECRETS_ENV_FILE ?= .env.user-secrets
G6_READONLY_CHROMA_PATH ?= data/chroma
G6_READONLY_CHROMA_SITE_PACKAGES ?= .venv-chroma-g6-20260811/lib/python3.11/site-packages
G7_RUN_ID ?=
G7_MYSQL_READONLY_RUN_ID ?=
G7_RECOMMENDATION_PLAN_RUN_ID ?=
G7_RECOMMENDATION_PLAN_BASELINE ?=
G7_RECOMMENDATION_APPLY_RUN_ID ?=
G7_RECOMMENDATION_PLAN ?=
G7_RECOMMENDATION_BASELINE ?=
G7_RECOMMENDATION_PLAN_HASH ?=
G7_RECOMMENDATION_REQUEST_RUN_ID ?=
G7_RECOMMENDATION_RECONCILE_RUN_ID ?=
G7_RECOMMENDATION_RECONCILE_PLAN ?=
G7_RECOMMENDATION_RECONCILE_BASELINE ?=
G7_RECOMMENDATION_RECONCILE_PLAN_HASH ?=
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
HOST_ENV_SYNC_RUN_ID ?=
G8_RELEASE_RUN_ID ?=
G8_FRONTEND_RUN_ID ?=
G8_BACKEND_IMAGE ?=
G8_DOCKER_CLI ?= $(DOCKER_CLI)
G8_ACCEPTANCE_COVERAGE_RUN_ID ?=
G8_FINAL_REVALIDATION_PLAN_RUN_ID ?=
G8_FINAL_REVALIDATION_AUDIT_RUN_ID ?=
G8_FINAL_REVALIDATION_PLAN ?=
G8_FINAL_RUNTIME_EVIDENCE ?=
LLM_REAL_CALL_READINESS_RUN_ID ?=
LLM_REAL_CALL_ENV_FILE ?= .env.host
LLM_FIXTURE_CALL_RUN_ID ?=
LLM_FIXTURE_CALL_CONFIRM ?=
G4_REAL_LLM_READONLY_RUN_ID ?=
G4_REAL_LLM_READONLY_CONFIRM ?=
G4_REAL_LLM_READONLY_COMPOSE_ENV_FILE ?= .env.compose
G4_REAL_LLM_READONLY_SECRETS_FILE ?= .env.user-secrets
G4_REAL_LLM_READONLY_LLM_ENV_FILE ?= .env.host
G4_REAL_LLM_READONLY_CHROMA_PATH ?= data/chroma
G4_REAL_LLM_READONLY_CHROMA_SITE_PACKAGES ?= .venv-chroma-g6-20260811/lib/python3.11/site-packages
G4_AGENT_AUTONOMY_RUN_ID ?=

.PHONY: \
	bootstrap bootstrap-check \
	plan-host-env-sync sync-host-env-from-compose verify-host-env \
	safety-check architecture-check docs-check contracts-check \
	test-g0 test-g1-python frontend-test frontend-build \
	test-g2 test-g3 test-g4 test-g5 test-g6 test-g7 test-g8 test-g9 g2-tools-install g2-dataset-report plan-g2-indexes verify-g0 verify-g1-local verify-g1-runtime verify-g1 verify-g2-local verify-g3-local verify-g4-local verify-g5-local \
	migrate-g2 migrate-g5 migrate-g5-audit seed-g2 replay-g2 verify-g2-runtime migrate-g3 migrate-g3-transition migrate-g3-clarification migrate-g4-agent-logs g3-demo verify-g3-runtime verify-g3-api-runtime verify-g3-clarification-runtime verify-g4-orchestrator verify-g4-agent-logs verify-g4-real-ports verify-g4-composition verify-g4-readonly-fusion verify-g5-runtime compose-config \
	verify-g5-http-runtime verify-g5-worker-prepare verify-g5-worker-resume verify-g5-audit-replay-runtime \
	verify-formal-auth-runtime \
	verify-experiment-freeze verify-evaluation-freeze-inputs verify-book-intake verify-data-plane-runtime \
	verify-prompt-bundle verify-llm-real-call-readiness execute-llm-fixture-call verify-g4-real-llm-readonly verify-g4-agent-autonomy \
	verify-g7-optin-http verify-g7-mysql-http-readonly build-g7-recommendation-post-plan execute-g7-recommendation-post verify-g7-recommendation-post-result \
	build-g4-recommendation-projection-plan execute-g4-recommendation-projection verify-g4-recommendation-projection-result verify-g4-clarification-readonly build-g4-clarification-plan execute-g4-clarification-plan verify-g4-clarification-continuation-readonly build-g4-clarification-continuation-plan execute-g4-clarification-continuation-plan \
	verify-g4-http-readonly-host verify-g5-feedback-http-readonly build-g5-feedback-http-plan execute-g5-feedback-worker-plan verify-g5-worker-wiring verify-g5-worker-readonly-runtime \
	verify-g8-release-preflight verify-g8-acceptance-coverage build-g8-final-revalidation-plan verify-g8-final-revalidation-plan \
	build-book-graph-plan verify-book-graph-plan import-book-graph \
	build-mysql-book-plan verify-mysql-book-plan preflight-mysql-book-catalog import-mysql-book-catalog \
	build-vector-index-plan verify-vector-index-plan build-chroma-collection-plan verify-chroma-collection-plan \
	preflight-chroma-import import-chroma-vectors import-chroma-vectors-idempotency verify-chroma-import verify-g6-readonly-fusion \
	start stop status infra-start infra-stop backend demo-backend frontend worker git-status

bootstrap-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/bootstrap.py

bootstrap:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/bootstrap.py --create-config

plan-host-env-sync:
	@test -n "$(HOST_ENV_SYNC_RUN_ID)" || { echo "HOST_ENV_SYNC_RUN_ID is required and must identify a new configuration plan"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.sync_host_env_from_compose --run-id "$(HOST_ENV_SYNC_RUN_ID)"

sync-host-env-from-compose:
	@test -n "$(HOST_ENV_SYNC_RUN_ID)" || { echo "HOST_ENV_SYNC_RUN_ID is required and must identify a new configuration apply"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.sync_host_env_from_compose --run-id "$(HOST_ENV_SYNC_RUN_ID)" --apply

verify-host-env:
	@test -f .env.host || { echo ".env.host is missing; run make bootstrap after installing prerequisites"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/validate_runtime_env.py --mode host --env-file .env.host

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

test-g7:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/g7 -t tests -p 'test_*.py'

test-g8:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/g8 -t tests -p 'test_*.py'

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

verify-g8-release-preflight:
	@test -n "$(G8_RELEASE_RUN_ID)" || { echo "G8_RELEASE_RUN_ID is required and must name a new evidence run"; exit 2; }
	@test -n "$(G8_FRONTEND_RUN_ID)" || { echo "G8_FRONTEND_RUN_ID is required and must name a new frontend build"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g8_release_preflight --run-id "$(G8_RELEASE_RUN_ID)" --frontend-run-id "$(G8_FRONTEND_RUN_ID)" --python "$(PYTHON)" --npm "$(NPM)" --docker-cli "$(G8_DOCKER_CLI)" $(if $(G8_BACKEND_IMAGE),--backend-image "$(G8_BACKEND_IMAGE)",)

verify-g8-acceptance-coverage:
	@test -n "$(G8_ACCEPTANCE_COVERAGE_RUN_ID)" || { echo "G8_ACCEPTANCE_COVERAGE_RUN_ID is required and must name a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g8_acceptance_coverage --run-id "$(G8_ACCEPTANCE_COVERAGE_RUN_ID)"

build-g8-final-revalidation-plan:
	@test -n "$(G8_FINAL_REVALIDATION_PLAN_RUN_ID)" || { echo "G8_FINAL_REVALIDATION_PLAN_RUN_ID is required and must name a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_g8_final_revalidation_plan --run-id "$(G8_FINAL_REVALIDATION_PLAN_RUN_ID)"

verify-g8-final-revalidation-plan:
	@test -n "$(G8_FINAL_REVALIDATION_AUDIT_RUN_ID)" || { echo "G8_FINAL_REVALIDATION_AUDIT_RUN_ID is required and must name a new evidence run"; exit 2; }
	@test -n "$(G8_FINAL_REVALIDATION_PLAN)" || { echo "G8_FINAL_REVALIDATION_PLAN is required and must point to an existing plan"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g8_final_revalidation_plan --run-id "$(G8_FINAL_REVALIDATION_AUDIT_RUN_ID)" --plan "$(G8_FINAL_REVALIDATION_PLAN)" $(if $(G8_FINAL_RUNTIME_EVIDENCE),--runtime-evidence "$(G8_FINAL_RUNTIME_EVIDENCE)",)

verify-g0: safety-check architecture-check docs-check contracts-check verify-prompt-bundle test-g0

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

verify-g5-feedback-http-readonly:
	@test -n "$(G5_FEEDBACK_HTTP_READONLY_RUN_ID)" || { echo "G5_FEEDBACK_HTTP_READONLY_RUN_ID is required and must identify a new read-only evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g5_feedback_http_readonly --run-id "$(G5_FEEDBACK_HTTP_READONLY_RUN_ID)" --env-file "$(G5_FEEDBACK_HTTP_READONLY_ENV_FILE)" --secrets-file "$(G5_FEEDBACK_HTTP_READONLY_SECRETS_FILE)"

build-g5-feedback-http-plan:
	@test -n "$(G5_FEEDBACK_PLAN_RUN_ID)" || { echo "G5_FEEDBACK_PLAN_RUN_ID is required and must identify a new DRY_RUN plan"; exit 2; }
	@test -n "$(G5_FEEDBACK_PLAN_BASELINE)" || { echo "G5_FEEDBACK_PLAN_BASELINE is required and must point to the PASS G5 feedback HTTP read-only evidence"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_g5_feedback_http_plan --run-id "$(G5_FEEDBACK_PLAN_RUN_ID)" --baseline "$(G5_FEEDBACK_PLAN_BASELINE)" --task-id "$(G5_FEEDBACK_PLAN_TASK_ID)" --record-id "$(G5_FEEDBACK_PLAN_RECORD_ID)" --item-id "$(G5_FEEDBACK_PLAN_ITEM_ID)" --resource-id "$(G5_FEEDBACK_PLAN_RESOURCE_ID)" --user-id "$(G5_FEEDBACK_PLAN_USER_ID)" --env-file "$(G5_FEEDBACK_HTTP_READONLY_ENV_FILE)" --secrets-file "$(G5_FEEDBACK_HTTP_READONLY_SECRETS_FILE)"

execute-g5-feedback-worker-plan:
	@test -n "$(G5_FEEDBACK_APPLY_RUN_ID)" || { echo "G5_FEEDBACK_APPLY_RUN_ID is required and must identify a new apply evidence run"; exit 2; }
	@test -n "$(G5_FEEDBACK_APPLY_PLAN)" || { echo "G5_FEEDBACK_APPLY_PLAN is required and must point to the approved G5 ChangePlan"; exit 2; }
	@test -n "$(G5_FEEDBACK_APPLY_PLAN_ID)" || { echo "G5_FEEDBACK_APPLY_PLAN_ID is required and must match the approved plan_id"; exit 2; }
	@test -n "$(G5_FEEDBACK_APPLY_PLAN_HASH)" || { echo "G5_FEEDBACK_APPLY_PLAN_HASH is required and must be the exact approved plan_hash"; exit 2; }
	@test -n "$(G5_FEEDBACK_APPLY_BASELINE)" || { echo "G5_FEEDBACK_APPLY_BASELINE is required and must point to the matching PASS read-only baseline"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.execute_g5_feedback_worker_plan --apply --plan "$(G5_FEEDBACK_APPLY_PLAN)" --plan-id "$(G5_FEEDBACK_APPLY_PLAN_ID)" --approved-plan-hash "$(G5_FEEDBACK_APPLY_PLAN_HASH)" --baseline "$(G5_FEEDBACK_APPLY_BASELINE)" --run-id "$(G5_FEEDBACK_APPLY_RUN_ID)" --env-file "$(G5_FEEDBACK_HTTP_READONLY_ENV_FILE)" --secrets-file "$(G5_FEEDBACK_HTTP_READONLY_SECRETS_FILE)"

verify-g5-feedback-worker-reconcile:
	@test -n "$(G5_FEEDBACK_RECONCILE_RUN_ID)" || { echo "G5_FEEDBACK_RECONCILE_RUN_ID is required and must identify a new read-only evidence run"; exit 2; }
	@test -n "$(G5_FEEDBACK_RECONCILE_PLAN)" || { echo "G5_FEEDBACK_RECONCILE_PLAN is required and must point to the attempted G5 ChangePlan"; exit 2; }
	@test -n "$(G5_FEEDBACK_RECONCILE_PLAN_ID)" || { echo "G5_FEEDBACK_RECONCILE_PLAN_ID is required and must match the attempted plan_id"; exit 2; }
	@test -n "$(G5_FEEDBACK_RECONCILE_PLAN_HASH)" || { echo "G5_FEEDBACK_RECONCILE_PLAN_HASH is required and must match the attempted plan_hash"; exit 2; }
	@test -n "$(G5_FEEDBACK_RECONCILE_BASELINE)" || { echo "G5_FEEDBACK_RECONCILE_BASELINE is required and must point to the matching PASS read-only baseline"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g5_feedback_worker_reconcile --plan "$(G5_FEEDBACK_RECONCILE_PLAN)" --plan-id "$(G5_FEEDBACK_RECONCILE_PLAN_ID)" --approved-plan-hash "$(G5_FEEDBACK_RECONCILE_PLAN_HASH)" --baseline "$(G5_FEEDBACK_RECONCILE_BASELINE)" --run-id "$(G5_FEEDBACK_RECONCILE_RUN_ID)" --env-file "$(G5_FEEDBACK_HTTP_READONLY_ENV_FILE)" --secrets-file "$(G5_FEEDBACK_HTTP_READONLY_SECRETS_FILE)"

verify-g5-worker-wiring:
	@test -n "$(G5_WORKER_WIRING_RUN_ID)" || { echo "G5_WORKER_WIRING_RUN_ID is required and must identify a new read-only evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g5_worker_wiring --run-id "$(G5_WORKER_WIRING_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g5-worker-readonly-runtime:
	@test -n "$(G5_WORKER_READONLY_RUN_ID)" || { echo "G5_WORKER_READONLY_RUN_ID is required and must identify a new read-only evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g5_worker_readonly_runtime --run-id "$(G5_WORKER_READONLY_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

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

verify-prompt-bundle:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_prompt_bundle

verify-llm-real-call-readiness:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_llm_real_call_readiness --env-file "$(LLM_REAL_CALL_ENV_FILE)" $(if $(LLM_REAL_CALL_READINESS_RUN_ID),--run-id "$(LLM_REAL_CALL_READINESS_RUN_ID)",)

execute-llm-fixture-call:
	@test -n "$(LLM_FIXTURE_CALL_RUN_ID)" || { echo "LLM_FIXTURE_CALL_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test "$(LLM_FIXTURE_CALL_CONFIRM)" = "YES_REAL_EXTERNAL_LLM" || { echo "LLM_FIXTURE_CALL_CONFIRM=YES_REAL_EXTERNAL_LLM is required"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.execute_llm_fixture_call --env-file "$(LLM_REAL_CALL_ENV_FILE)" --run-id "$(LLM_FIXTURE_CALL_RUN_ID)" --confirm "$(LLM_FIXTURE_CALL_CONFIRM)"

verify-g4-real-llm-readonly:
	@test -n "$(G4_REAL_LLM_READONLY_RUN_ID)" || { echo "G4_REAL_LLM_READONLY_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test "$(G4_REAL_LLM_READONLY_CONFIRM)" = "YES_REAL_EXTERNAL_LLM" || { echo "G4_REAL_LLM_READONLY_CONFIRM=YES_REAL_EXTERNAL_LLM is required"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_real_llm_readonly --compose-env-file "$(G4_REAL_LLM_READONLY_COMPOSE_ENV_FILE)" --secrets-file "$(G4_REAL_LLM_READONLY_SECRETS_FILE)" --llm-env-file "$(G4_REAL_LLM_READONLY_LLM_ENV_FILE)" --chroma-path "$(G4_REAL_LLM_READONLY_CHROMA_PATH)" --chroma-site-packages "$(G4_REAL_LLM_READONLY_CHROMA_SITE_PACKAGES)" --run-id "$(G4_REAL_LLM_READONLY_RUN_ID)" --confirm "$(G4_REAL_LLM_READONLY_CONFIRM)"

verify-g4-agent-autonomy:
	@test -n "$(G4_AGENT_AUTONOMY_RUN_ID)" || { echo "G4_AGENT_AUTONOMY_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_agent_autonomy_runtime --run-id "$(G4_AGENT_AUTONOMY_RUN_ID)"

verify-g7-optin-http:
	@test -n "$(G7_RUN_ID)" || { echo "G7_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g7_optin_http --run-id "$(G7_RUN_ID)"

verify-g7-mysql-http-readonly:
	@test -n "$(G7_MYSQL_READONLY_RUN_ID)" || { echo "G7_MYSQL_READONLY_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g7_mysql_http_readonly --run-id "$(G7_MYSQL_READONLY_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

build-g7-recommendation-post-plan:
	@test -n "$(G7_RECOMMENDATION_PLAN_RUN_ID)" || { echo "G7_RECOMMENDATION_PLAN_RUN_ID is required and must identify a new plan run"; exit 2; }
	@test -n "$(G7_RECOMMENDATION_PLAN_BASELINE)" || { echo "G7_RECOMMENDATION_PLAN_BASELINE is required and must point to a PASS read-only evidence file"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_g7_recommendation_post_plan --run-id "$(G7_RECOMMENDATION_PLAN_RUN_ID)" --baseline "$(G7_RECOMMENDATION_PLAN_BASELINE)"

build-g4-recommendation-projection-plan:
	@test -n "$(G4_PROJECTION_PLAN_RUN_ID)" || { echo "G4_PROJECTION_PLAN_RUN_ID is required and must identify a new dry-run plan"; exit 2; }
	@test -n "$(G4_PROJECTION_MYSQL_BASELINE)" || { echo "G4_PROJECTION_MYSQL_BASELINE is required and must point to a PASS MySQL read-only evidence file"; exit 2; }
	@test -n "$(G4_PROJECTION_G4_BASELINE)" || { echo "G4_PROJECTION_G4_BASELINE is required and must point to a PASS G4 read-only evidence file"; exit 2; }
	@test "$(G4_PROJECTION_REQUEST_ID)" = "$(G4_PROJECTION_SESSION_ID)" || { test -n "$(G4_PROJECTION_REQUEST_ID)" -a -n "$(G4_PROJECTION_SESSION_ID)" || { echo "G4_PROJECTION_REQUEST_ID and G4_PROJECTION_SESSION_ID must be supplied together"; exit 2; }; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_g4_recommendation_projection_plan --run-id "$(G4_PROJECTION_PLAN_RUN_ID)" --mysql-baseline "$(G4_PROJECTION_MYSQL_BASELINE)" --g4-baseline "$(G4_PROJECTION_G4_BASELINE)" --user-id "$(G4_PROJECTION_USER_ID)" --input-text "$(G4_PROJECTION_INPUT_TEXT)" --limit "$(G4_PROJECTION_LIMIT)" $(if $(G4_PROJECTION_REQUEST_ID),--request-id "$(G4_PROJECTION_REQUEST_ID)" --session-id "$(G4_PROJECTION_SESSION_ID)",)

verify-g4-clarification-readonly:
	@test -n "$(G4_CLARIFICATION_READONLY_RUN_ID)" || { echo "G4_CLARIFICATION_READONLY_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_clarification_readonly --run-id "$(G4_CLARIFICATION_READONLY_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --secrets-file ".env.user-secrets"

build-g4-clarification-plan:
	@test -n "$(G4_CLARIFICATION_PLAN_RUN_ID)" || { echo "G4_CLARIFICATION_PLAN_RUN_ID is required and must identify a new dry-run plan"; exit 2; }
	@test -n "$(G4_CLARIFICATION_PLAN_EVIDENCE)" || { echo "G4_CLARIFICATION_PLAN_EVIDENCE is required and must point to PASS clarification read-only evidence"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_g4_clarification_plan --run-id "$(G4_CLARIFICATION_PLAN_RUN_ID)" --evidence "$(G4_CLARIFICATION_PLAN_EVIDENCE)"

verify-g4-clarification-continuation-readonly:
	@test -n "$(G4_CLARIFICATION_CONTINUATION_READONLY_RUN_ID)" || { echo "G4_CLARIFICATION_CONTINUATION_READONLY_RUN_ID is required"; exit 2; }
	@test -n "$(G4_CLARIFICATION_CONTINUATION_TASK_ID)" || { echo "G4_CLARIFICATION_CONTINUATION_TASK_ID is required"; exit 2; }
	@test -n "$(G4_CLARIFICATION_CONTINUATION_RESOURCE_TYPES)" || { echo "G4_CLARIFICATION_CONTINUATION_RESOURCE_TYPES is required"; exit 2; }
	@test -n "$(G4_CLARIFICATION_CONTINUATION_TOPIC)" || { echo "G4_CLARIFICATION_CONTINUATION_TOPIC is required"; exit 2; }
	@test -n "$(G4_CLARIFICATION_CONTINUATION_IDEMPOTENCY_KEY)" || { echo "G4_CLARIFICATION_CONTINUATION_IDEMPOTENCY_KEY is required"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_clarification_continuation_readonly --run-id "$(G4_CLARIFICATION_CONTINUATION_READONLY_RUN_ID)" --task-id "$(G4_CLARIFICATION_CONTINUATION_TASK_ID)" --context-version "$(G4_CLARIFICATION_CONTINUATION_CONTEXT_VERSION)" --resource-types "$(G4_CLARIFICATION_CONTINUATION_RESOURCE_TYPES)" --topic "$(G4_CLARIFICATION_CONTINUATION_TOPIC)" --idempotency-key "$(G4_CLARIFICATION_CONTINUATION_IDEMPOTENCY_KEY)" --env-file "$(COMPOSE_ENV_FILE)" --secrets-file ".env.user-secrets"

build-g4-clarification-continuation-plan:
	@test -n "$(G4_CLARIFICATION_CONTINUATION_PLAN_RUN_ID)" || { echo "G4_CLARIFICATION_CONTINUATION_PLAN_RUN_ID is required"; exit 2; }
	@test -n "$(G4_CLARIFICATION_CONTINUATION_EVIDENCE)" || { echo "G4_CLARIFICATION_CONTINUATION_EVIDENCE is required"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.build_g4_clarification_continuation_plan --run-id "$(G4_CLARIFICATION_CONTINUATION_PLAN_RUN_ID)" --evidence "$(G4_CLARIFICATION_CONTINUATION_EVIDENCE)"

execute-g4-clarification-continuation-plan:
	@test -n "$(G4_CLARIFICATION_CONTINUATION_APPLY_RUN_ID)" || { echo "G4_CLARIFICATION_CONTINUATION_APPLY_RUN_ID is required"; exit 2; }
	@test -n "$(G4_CLARIFICATION_CONTINUATION_PLAN)" || { echo "G4_CLARIFICATION_CONTINUATION_PLAN is required"; exit 2; }
	@test -n "$(G4_CLARIFICATION_CONTINUATION_PLAN_ID)" || { echo "G4_CLARIFICATION_CONTINUATION_PLAN_ID is required"; exit 2; }
	@test -n "$(G4_CLARIFICATION_CONTINUATION_PLAN_HASH)" || { echo "G4_CLARIFICATION_CONTINUATION_PLAN_HASH is required"; exit 2; }
	@test -n "$(G4_CLARIFICATION_CONTINUATION_EVIDENCE)" || { echo "G4_CLARIFICATION_CONTINUATION_EVIDENCE is required"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.execute_g4_clarification_continuation_plan --apply --plan-id "$(G4_CLARIFICATION_CONTINUATION_PLAN_ID)" --approved-plan-hash "$(G4_CLARIFICATION_CONTINUATION_PLAN_HASH)" --plan "$(G4_CLARIFICATION_CONTINUATION_PLAN)" --evidence "$(G4_CLARIFICATION_CONTINUATION_EVIDENCE)" --run-id "$(G4_CLARIFICATION_CONTINUATION_APPLY_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --secrets-file ".env.user-secrets"

execute-g4-clarification-plan:
	@test -n "$(G4_CLARIFICATION_APPLY_RUN_ID)" || { echo "G4_CLARIFICATION_APPLY_RUN_ID is required and must identify a new apply evidence run"; exit 2; }
	@test -n "$(G4_CLARIFICATION_PLAN)" || { echo "G4_CLARIFICATION_PLAN is required and must point to the reviewed waiting ChangePlan"; exit 2; }
	@test -n "$(G4_CLARIFICATION_PLAN_ID)" || { echo "G4_CLARIFICATION_PLAN_ID is required and must match the reviewed plan_id"; exit 2; }
	@test -n "$(G4_CLARIFICATION_PLAN_HASH)" || { echo "G4_CLARIFICATION_PLAN_HASH is required and must be the exact approved hash"; exit 2; }
	@test -n "$(G4_CLARIFICATION_PLAN_EVIDENCE)" || { echo "G4_CLARIFICATION_PLAN_EVIDENCE is required and must point to the matching PASS read-only evidence"; exit 2; }
	@test -n "$(G4_CLARIFICATION_REQUEST_RUN_ID)" || { echo "G4_CLARIFICATION_REQUEST_RUN_ID is required and must identify the reviewed request payload"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.execute_g4_clarification_plan --apply --plan-id "$(G4_CLARIFICATION_PLAN_ID)" --approved-plan-hash "$(G4_CLARIFICATION_PLAN_HASH)" --plan "$(G4_CLARIFICATION_PLAN)" --evidence "$(G4_CLARIFICATION_PLAN_EVIDENCE)" --request-run-id "$(G4_CLARIFICATION_REQUEST_RUN_ID)" --run-id "$(G4_CLARIFICATION_APPLY_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --secrets-file ".env.user-secrets"

execute-g4-recommendation-projection:
	@test -n "$(G4_PROJECTION_APPLY_RUN_ID)" || { echo "G4_PROJECTION_APPLY_RUN_ID is required and must identify a new apply evidence run"; exit 2; }
	@test -n "$(G4_PROJECTION_PLAN)" || { echo "G4_PROJECTION_PLAN is required and must point to the reviewed G4 ChangePlan"; exit 2; }
	@test -n "$(G4_PROJECTION_PLAN_ID)" || { echo "G4_PROJECTION_PLAN_ID is required and must match the reviewed plan_id"; exit 2; }
	@test -n "$(G4_PROJECTION_PLAN_HASH)" || { echo "G4_PROJECTION_PLAN_HASH is required and must be the exact approved hash"; exit 2; }
	@test -n "$(G4_PROJECTION_MYSQL_BASELINE)" || { echo "G4_PROJECTION_MYSQL_BASELINE is required and must point to the matching PASS MySQL evidence"; exit 2; }
	@test -n "$(G4_PROJECTION_G4_BASELINE)" || { echo "G4_PROJECTION_G4_BASELINE is required and must point to the matching PASS G4 evidence"; exit 2; }
	@test -n "$(G4_PROJECTION_REQUEST_RUN_ID)" || { echo "G4_PROJECTION_REQUEST_RUN_ID is required and must identify the reviewed request payload"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.execute_g4_recommendation_projection --apply --plan-id "$(G4_PROJECTION_PLAN_ID)" --approved-plan-hash "$(G4_PROJECTION_PLAN_HASH)" --plan "$(G4_PROJECTION_PLAN)" --mysql-baseline "$(G4_PROJECTION_MYSQL_BASELINE)" --g4-baseline "$(G4_PROJECTION_G4_BASELINE)" --request-run-id "$(G4_PROJECTION_REQUEST_RUN_ID)" --run-id "$(G4_PROJECTION_APPLY_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g4-recommendation-projection-result:
	@test -n "$(G4_PROJECTION_RECONCILE_RUN_ID)" || { echo "G4_PROJECTION_RECONCILE_RUN_ID is required and must identify a new reconciliation evidence run"; exit 2; }
	@test -n "$(G4_PROJECTION_PLAN)" || { echo "G4_PROJECTION_PLAN is required and must point to the approved G4 ChangePlan"; exit 2; }
	@test -n "$(G4_PROJECTION_PLAN_ID)" || { echo "G4_PROJECTION_PLAN_ID is required and must match the approved plan_id"; exit 2; }
	@test -n "$(G4_PROJECTION_PLAN_HASH)" || { echo "G4_PROJECTION_PLAN_HASH is required and must be the approved plan hash"; exit 2; }
	@test -n "$(G4_PROJECTION_RECONCILE_APPLY_EVIDENCE)" || { echo "G4_PROJECTION_RECONCILE_APPLY_EVIDENCE is required and must point to PASS apply evidence"; exit 2; }
	@test -n "$(G4_PROJECTION_REQUEST_RUN_ID)" || { echo "G4_PROJECTION_REQUEST_RUN_ID is required and must identify the approved request payload"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_recommendation_projection_result --plan-id "$(G4_PROJECTION_PLAN_ID)" --approved-plan-hash "$(G4_PROJECTION_PLAN_HASH)" --plan "$(G4_PROJECTION_PLAN)" --apply-evidence "$(G4_PROJECTION_RECONCILE_APPLY_EVIDENCE)" --request-run-id "$(G4_PROJECTION_REQUEST_RUN_ID)" --run-id "$(G4_PROJECTION_RECONCILE_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)" --secrets-file "$(G6_READONLY_SECRETS_ENV_FILE)" --chroma-path "$(G6_READONLY_CHROMA_PATH)" --chroma-site-packages "$(G6_READONLY_CHROMA_SITE_PACKAGES)"

execute-g7-recommendation-post:
	@test -n "$(G7_RECOMMENDATION_APPLY_RUN_ID)" || { echo "G7_RECOMMENDATION_APPLY_RUN_ID is required and must identify a new apply evidence run"; exit 2; }
	@test -n "$(G7_RECOMMENDATION_PLAN)" || { echo "G7_RECOMMENDATION_PLAN is required and must point to the reviewed ChangePlan"; exit 2; }
	@test -n "$(G7_RECOMMENDATION_BASELINE)" || { echo "G7_RECOMMENDATION_BASELINE is required and must point to the matching PASS read-only evidence"; exit 2; }
	@test -n "$(G7_RECOMMENDATION_PLAN_HASH)" || { echo "G7_RECOMMENDATION_PLAN_HASH is required and must be the exact approved hash"; exit 2; }
	@test -n "$(G7_RECOMMENDATION_REQUEST_RUN_ID)" || { echo "G7_RECOMMENDATION_REQUEST_RUN_ID is required and must identify the reviewed request payload"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.execute_g7_recommendation_post --apply --approved-plan-hash "$(G7_RECOMMENDATION_PLAN_HASH)" --plan "$(G7_RECOMMENDATION_PLAN)" --baseline "$(G7_RECOMMENDATION_BASELINE)" --request-run-id "$(G7_RECOMMENDATION_REQUEST_RUN_ID)" --run-id "$(G7_RECOMMENDATION_APPLY_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g7-recommendation-post-result:
	@test -n "$(G7_RECOMMENDATION_RECONCILE_RUN_ID)" || { echo "G7_RECOMMENDATION_RECONCILE_RUN_ID is required and must identify a new reconciliation evidence run"; exit 2; }
	@test -n "$(G7_RECOMMENDATION_RECONCILE_PLAN)" || { echo "G7_RECOMMENDATION_RECONCILE_PLAN is required and must point to the reviewed ChangePlan"; exit 2; }
	@test -n "$(G7_RECOMMENDATION_RECONCILE_BASELINE)" || { echo "G7_RECOMMENDATION_RECONCILE_BASELINE is required and must point to the matching PASS read-only evidence"; exit 2; }
	@test -n "$(G7_RECOMMENDATION_RECONCILE_PLAN_HASH)" || { echo "G7_RECOMMENDATION_RECONCILE_PLAN_HASH is required and must be the exact approved hash"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g7_recommendation_post_result --approved-plan-hash "$(G7_RECOMMENDATION_RECONCILE_PLAN_HASH)" --plan "$(G7_RECOMMENDATION_RECONCILE_PLAN)" --baseline "$(G7_RECOMMENDATION_RECONCILE_BASELINE)" --run-id "$(G7_RECOMMENDATION_RECONCILE_RUN_ID)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g6-readonly-fusion:
	@test -n "$(G6_READONLY_RUN_ID)" || { echo "G6_READONLY_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g6_readonly_fusion --run-id "$(G6_READONLY_RUN_ID)" --env-file "$(G6_READONLY_MYSQL_ENV_FILE)" --secrets-file "$(G6_READONLY_SECRETS_ENV_FILE)" --chroma-path "$(G6_READONLY_CHROMA_PATH)" --chroma-site-packages "$(G6_READONLY_CHROMA_SITE_PACKAGES)"

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

verify-g4-readonly-fusion:
	@test -n "$(G4_READONLY_FUSION_RUN_ID)" || { echo "G4_READONLY_FUSION_RUN_ID is required and must identify a new evidence run"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_readonly_fusion_runtime --run-id "$(G4_READONLY_FUSION_RUN_ID)" --deadline-seconds "$(G4_READONLY_FUSION_DEADLINE_SECONDS)" --env-file "$(COMPOSE_ENV_FILE)"

verify-g4-http-readonly-host:
	@test -n "$(G4_HTTP_READONLY_HOST_RUN_ID)" || { echo "G4_HTTP_READONLY_HOST_RUN_ID is required and must identify a new evidence run"; exit 2; }
	@test "$(G4_HTTP_READONLY_HOST_CONFIRM)" = "YES_READONLY" || { echo "G4_HTTP_READONLY_HOST_CONFIRM=YES_READONLY is required; this target only performs GET/SELECT checks"; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.verify_g4_http_host_readonly --run-id "$(G4_HTTP_READONLY_HOST_RUN_ID)" --confirm-readonly --env-file "$(COMPOSE_ENV_FILE)" --secrets-file "$(G6_READONLY_SECRETS_ENV_FILE)" --chroma-path "$(G6_READONLY_CHROMA_PATH)" --chroma-site-packages "$(G6_READONLY_CHROMA_SITE_PACKAGES)"

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

demo-backend:
	@test -f "$(DEMO_BACKEND_ENV_FILE)" || { echo "DEMO_BACKEND_ENV_FILE is missing: $(DEMO_BACKEND_ENV_FILE)"; exit 2; }
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/validate_runtime_env.py --mode host --env-file "$(DEMO_BACKEND_ENV_FILE)"
	@set -a; . "$(DEMO_BACKEND_ENV_FILE)"; set +a; RECPRO_APP_ENV=demo RECPRO_DEMO_HTTP_ENABLED=true exec $(PYTHON) -m uvicorn backend.app.demo_main:app --host 127.0.0.1 --port "$(DEMO_BACKEND_PORT)" --reload

frontend:
	$(NPM) --prefix frontend run dev

worker:
	@test -f .env.host || { echo ".env.host is missing; run make bootstrap after installing prerequisites"; exit 2; }
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/validate_runtime_env.py --mode host --env-file .env.host
	@set -a; . ./.env.host; set +a; exec $(PYTHON) -m backend.app.worker

git-status:
	git status --short --branch
