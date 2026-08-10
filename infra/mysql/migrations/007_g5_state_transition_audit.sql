-- G5 append-only state-transition audit facts.
-- Current-projection and technical-state writes must append one row in the
-- same transaction. This migration creates no destructive path.

CREATE TABLE IF NOT EXISTS domain_state_transition (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    transition_uuid CHAR(36) NOT NULL,
    module_name VARCHAR(32) NOT NULL,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id VARCHAR(128) NOT NULL,
    transition_type VARCHAR(64) NOT NULL,
    from_state VARCHAR(64) NULL,
    to_state VARCHAR(64) NOT NULL,
    version_before INT UNSIGNED NULL,
    version_after INT UNSIGNED NOT NULL,
    causation_ref VARCHAR(255) NOT NULL,
    actor_type VARCHAR(32) NOT NULL,
    actor_ref VARCHAR(128) NULL,
    detail_json JSON NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_domain_transition_uuid (transition_uuid),
    UNIQUE KEY uq_domain_transition_aggregate_version (aggregate_type, aggregate_id, version_after),
    KEY ix_domain_transition_aggregate (aggregate_type, aggregate_id, id),
    KEY ix_domain_transition_created (created_at, module_name),
    CONSTRAINT chk_domain_transition_version CHECK (
        (version_before IS NULL AND version_after = 1)
        OR (version_before IS NOT NULL AND version_after > version_before)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g5-state-transition-audit-v1', 'forward-only-g5-state-transition-audit-v1', UTC_TIMESTAMP(3));
