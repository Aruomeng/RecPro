-- G3 forward-only MySQL recommendation slice. Never alter or remove G2 facts.

CREATE TABLE IF NOT EXISTS recommendation_task (
    id CHAR(36) NOT NULL,
    request_id CHAR(36) NOT NULL,
    trace_id CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    session_id CHAR(36) NOT NULL,
    trigger_scene VARCHAR(32) NOT NULL,
    input_text TEXT NULL,
    request_json JSON NOT NULL,
    intent_type VARCHAR(48) NOT NULL,
    intent_confidence DECIMAL(7,6) NOT NULL,
    status VARCHAR(32) NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    profile_version INT UNSIGNED NULL,
    config_bundle_version VARCHAR(64) NOT NULL,
    policy_version VARCHAR(64) NOT NULL,
    ranking_version VARCHAR(64) NOT NULL,
    behavior_formula_version VARCHAR(64) NOT NULL,
    dataset_version VARCHAR(64) NOT NULL,
    replan_count TINYINT UNSIGNED NOT NULL DEFAULT 0,
    evaluation_at DATETIME(3) NOT NULL,
    started_at DATETIME(3) NOT NULL,
    finished_at DATETIME(3) NULL,
    error_code VARCHAR(64) NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_task_request (user_id, request_id),
    UNIQUE KEY uq_recommendation_task_trace (trace_id),
    KEY ix_recommendation_task_status (user_id, status, created_at),
    CONSTRAINT chk_recommendation_task_confidence CHECK (intent_confidence >= 0 AND intent_confidence <= 1),
    CONSTRAINT chk_recommendation_task_replan CHECK (replan_count <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_candidate (
    task_id CHAR(36) NOT NULL,
    plan_version TINYINT UNSIGNED NOT NULL,
    resource_id BIGINT UNSIGNED NOT NULL,
    channel VARCHAR(16) NOT NULL,
    channel_rank INT UNSIGNED NOT NULL,
    raw_score DECIMAL(12,6) NOT NULL,
    normalized_score DECIMAL(7,6) NOT NULL,
    rrf_contribution DECIMAL(12,6) NOT NULL,
    evidence_json JSON NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (task_id, plan_version, resource_id, channel),
    KEY ix_recommendation_candidate_resource (resource_id, created_at),
    CONSTRAINT fk_recommendation_candidate_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_candidate_rank CHECK (channel_rank > 0),
    CONSTRAINT chk_recommendation_candidate_normalized CHECK (normalized_score >= 0 AND normalized_score <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_record (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_id CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    output_type VARCHAR(32) NOT NULL,
    delivery_strategy VARCHAR(16) NOT NULL,
    ranking_version VARCHAR(64) NOT NULL,
    decision_json JSON NOT NULL,
    warnings_json JSON NOT NULL,
    versions_json JSON NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_record_task (task_id),
    CONSTRAINT fk_recommendation_record_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_item (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    record_id BIGINT UNSIGNED NOT NULL,
    resource_id BIGINT UNSIGNED NOT NULL,
    rank_no INT UNSIGNED NOT NULL,
    relevance_score DECIMAL(12,6) NOT NULL,
    final_score DECIMAL(12,6) NOT NULL,
    mmr_score DECIMAL(12,6) NOT NULL,
    evidence_confidence DECIMAL(7,6) NOT NULL,
    primary_channel VARCHAR(16) NOT NULL,
    score_detail_json JSON NOT NULL,
    reason_evidence_json JSON NOT NULL,
    diversity_relaxed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_item_resource (record_id, resource_id),
    UNIQUE KEY uq_recommendation_item_rank (record_id, rank_no),
    KEY ix_recommendation_item_resource (resource_id),
    CONSTRAINT fk_recommendation_item_record FOREIGN KEY (record_id) REFERENCES recommendation_record (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_item_rank CHECK (rank_no > 0),
    CONSTRAINT chk_recommendation_item_confidence CHECK (evidence_confidence >= 0 AND evidence_confidence <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_item_explanation (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    recommendation_item_id BIGINT UNSIGNED NOT NULL,
    explanation_version INT UNSIGNED NOT NULL,
    explanation_text TEXT NOT NULL,
    effective_explanation_level VARCHAR(16) NOT NULL,
    provider VARCHAR(16) NOT NULL,
    validator_status VARCHAR(24) NOT NULL,
    evidence_refs_json JSON NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_explanation_version (recommendation_item_id, explanation_version),
    CONSTRAINT fk_recommendation_explanation_item FOREIGN KEY (recommendation_item_id) REFERENCES recommendation_item (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_trace (
    trace_id CHAR(36) NOT NULL,
    task_id CHAR(36) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    steps_json JSON NOT NULL,
    complete BOOLEAN NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (trace_id),
    UNIQUE KEY uq_recommendation_trace_task (task_id),
    CONSTRAINT fk_recommendation_trace_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g3-recommendation-v1', 'forward-only-g3-recommendation-v1', UTC_TIMESTAMP(3));
