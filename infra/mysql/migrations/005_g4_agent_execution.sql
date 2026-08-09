-- G4 forward-only Agent execution and orchestration facts.
-- Every row is append-only and the application owns the surrounding transaction.

CREATE TABLE IF NOT EXISTS recommendation_agent_message (
    message_id CHAR(36) NOT NULL,
    task_id CHAR(36) NOT NULL,
    trace_id CHAR(36) NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    sender VARCHAR(128) NOT NULL,
    receiver VARCHAR(128) NOT NULL,
    message_type VARCHAR(64) NOT NULL,
    payload_json JSON NOT NULL,
    deadline_at DATETIME(3) NOT NULL,
    attempt INT UNSIGNED NOT NULL,
    idempotency_key CHAR(255) NOT NULL,
    causation_id CHAR(36) NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (message_id),
    UNIQUE KEY uq_recommendation_agent_message_idempotency (task_id, idempotency_key),
    KEY ix_recommendation_agent_message_task (task_id, created_at),
    CONSTRAINT fk_recommendation_agent_message_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_agent_message_context CHECK (context_version > 0),
    CONSTRAINT chk_recommendation_agent_message_attempt CHECK (attempt > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_agent_result (
    result_id CHAR(36) NOT NULL,
    message_id CHAR(36) NOT NULL,
    task_id CHAR(36) NOT NULL,
    trace_id CHAR(36) NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    agent_name VARCHAR(128) NOT NULL,
    agent_version VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    confidence DECIMAL(7,6) NOT NULL,
    payload_json JSON NULL,
    evidence_refs_json JSON NOT NULL,
    warnings_json JSON NOT NULL,
    fallback_used BOOLEAN NOT NULL,
    tool_calls_json JSON NOT NULL,
    error_code VARCHAR(128) NULL,
    duration_ms INT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (result_id),
    UNIQUE KEY uq_recommendation_agent_result_message (message_id),
    KEY ix_recommendation_agent_result_task (task_id, context_version, created_at),
    CONSTRAINT fk_recommendation_agent_result_message FOREIGN KEY (message_id) REFERENCES recommendation_agent_message (message_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_recommendation_agent_result_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_agent_result_context CHECK (context_version > 0),
    CONSTRAINT chk_recommendation_agent_result_confidence CHECK (confidence >= 0 AND confidence <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_agent_artifact (
    artifact_id CHAR(36) NOT NULL,
    task_id CHAR(36) NOT NULL,
    trace_id CHAR(36) NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    artifact_type VARCHAR(64) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    metadata_json JSON NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (artifact_id),
    UNIQUE KEY uq_recommendation_agent_artifact_content (task_id, artifact_type, content_hash),
    KEY ix_recommendation_agent_artifact_task (task_id, context_version, created_at),
    CONSTRAINT fk_recommendation_agent_artifact_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_agent_artifact_context CHECK (context_version > 0),
    CONSTRAINT chk_recommendation_agent_artifact_hash CHECK (CHAR_LENGTH(content_hash) = 64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_orchestration_result (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_id CHAR(36) NOT NULL,
    trace_id CHAR(36) NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    replan_count TINYINT UNSIGNED NOT NULL,
    payload_json JSON NOT NULL,
    transitions_json JSON NOT NULL,
    trace_json JSON NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_orchestration_result_context (task_id, context_version),
    KEY ix_recommendation_orchestration_result_trace (trace_id, created_at),
    CONSTRAINT fk_recommendation_orchestration_result_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_orchestration_result_context CHECK (context_version > 0),
    CONSTRAINT chk_recommendation_orchestration_result_replan CHECK (replan_count <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g4-agent-execution-v1', 'forward-only-g4-agent-execution-v1', UTC_TIMESTAMP(3));
