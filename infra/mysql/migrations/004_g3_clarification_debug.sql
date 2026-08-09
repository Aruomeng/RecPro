-- G3 forward-only clarification and research-debug facts.
-- Every row is an immutable version/event.  No migration statement rewrites
-- or removes an existing fact.

CREATE TABLE IF NOT EXISTS recommendation_task_context (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_id CHAR(36) NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    request_json JSON NOT NULL,
    questions_json JSON NOT NULL,
    answers_json JSON NOT NULL,
    response_json JSON NOT NULL,
    idempotency_key CHAR(255) NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_context_version (task_id, context_version),
    UNIQUE KEY uq_recommendation_context_idempotency (task_id, idempotency_key),
    KEY ix_recommendation_context_latest (task_id, context_version),
    CONSTRAINT fk_recommendation_context_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_context_version CHECK (context_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_clarification (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_id CHAR(36) NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    questions_json JSON NOT NULL,
    answers_json JSON NOT NULL,
    asked_at DATETIME(3) NOT NULL,
    answered_at DATETIME(3) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_clarification_context (task_id, context_version),
    CONSTRAINT fk_recommendation_clarification_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_clarification_version CHECK (context_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_policy_decision (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_id CHAR(36) NOT NULL,
    decision_no INT UNSIGNED NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    plan_version TINYINT UNSIGNED NULL,
    output_type VARCHAR(32) NOT NULL,
    delivery_strategy VARCHAR(16) NOT NULL,
    explanation_level VARCHAR(16) NOT NULL,
    adaptation_state VARCHAR(24) NOT NULL,
    decision_reason_codes_json JSON NOT NULL,
    decision_reason VARCHAR(1000) NOT NULL,
    policy_version VARCHAR(64) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_policy_decision (task_id, decision_no),
    KEY ix_recommendation_policy_context (task_id, context_version, decision_no),
    CONSTRAINT fk_recommendation_policy_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_policy_decision_no CHECK (decision_no > 0),
    CONSTRAINT chk_recommendation_policy_context CHECK (context_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_trace_revision (
    trace_id CHAR(36) NOT NULL,
    task_id CHAR(36) NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    steps_json JSON NOT NULL,
    complete BOOLEAN NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (trace_id),
    UNIQUE KEY uq_recommendation_trace_revision (task_id, context_version),
    CONSTRAINT fk_recommendation_trace_revision_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_trace_revision_context CHECK (context_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g3-clarification-debug-v1', 'forward-only-g3-clarification-debug-v1', UTC_TIMESTAMP(3));
