-- G3 forward-only task transition audit. It never rewrites or removes G2/G3 facts.

CREATE TABLE IF NOT EXISTS recommendation_task_transition (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_id CHAR(36) NOT NULL,
    context_version INT UNSIGNED NOT NULL,
    from_status VARCHAR(32) NOT NULL,
    to_status VARCHAR(32) NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    occurred_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_transition (task_id, context_version, to_status),
    KEY ix_recommendation_transition_task (task_id, id),
    CONSTRAINT fk_recommendation_transition_task FOREIGN KEY (task_id) REFERENCES recommendation_task (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_transition_context CHECK (context_version > 0),
    CONSTRAINT chk_recommendation_transition_status CHECK (from_status <> to_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g3-task-transition-v1', 'forward-only-g3-task-transition-v1', UTC_TIMESTAMP(3));
