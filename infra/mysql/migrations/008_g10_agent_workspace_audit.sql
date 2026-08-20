-- G10 append-only public Agent workspace audit facts.
-- This forward migration creates new objects only and leaves every existing
-- schema object and business fact unchanged.

CREATE TABLE IF NOT EXISTS agent_workspace_event (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    event_uuid CHAR(36) NOT NULL,
    workspace_id CHAR(36) NOT NULL,
    session_id CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    event_sequence INT UNSIGNED NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    agent_name VARCHAR(64) NULL,
    action_name VARCHAR(80) NULL,
    target_name VARCHAR(80) NULL,
    reason_code VARCHAR(120) NULL,
    confidence DECIMAL(6,5) NULL,
    public_payload_json JSON NULL,
    payload_sha256 CHAR(64) NOT NULL,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    PRIMARY KEY (id),
    UNIQUE KEY uq_agent_workspace_event_uuid (event_uuid),
    UNIQUE KEY uq_agent_workspace_event_sequence (workspace_id, event_sequence),
    KEY ix_agent_workspace_event_session (session_id, id),
    KEY ix_agent_workspace_event_user_time (user_id, occurred_at),
    KEY ix_agent_workspace_event_agent_time (agent_name, occurred_at),
    CONSTRAINT chk_agent_workspace_event_confidence CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS interaction_directive_fact (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    fact_uuid CHAR(36) NOT NULL,
    directive_id CHAR(36) NOT NULL,
    workspace_id CHAR(36) NOT NULL,
    session_id CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    directive_version INT UNSIGNED NOT NULL,
    directive_type VARCHAR(64) NOT NULL,
    directive_scope VARCHAR(80) NOT NULL,
    behavior VARCHAR(24) NOT NULL,
    fact_state VARCHAR(24) NOT NULL,
    reason_codes_json JSON NOT NULL,
    evidence_refs_json JSON NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    confidence DECIMAL(6,5) NOT NULL,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    PRIMARY KEY (id),
    UNIQUE KEY uq_interaction_directive_fact_uuid (fact_uuid),
    UNIQUE KEY uq_interaction_directive_state (directive_id, directive_version, fact_state),
    KEY ix_interaction_directive_workspace (workspace_id, id),
    KEY ix_interaction_directive_user_time (user_id, occurred_at),
    KEY ix_interaction_directive_type_state (directive_type, fact_state, occurred_at),
    CONSTRAINT chk_interaction_directive_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT chk_interaction_directive_behavior CHECK (behavior IN ('AUTO_APPLY', 'SUGGESTION', 'NOTICE')),
    CONSTRAINT chk_interaction_directive_state CHECK (
        fact_state IN ('PROPOSED', 'AUTO_APPLIED', 'ACCEPTED', 'DISMISSED', 'UNDONE', 'EXPIRED', 'SUPERSEDED')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g10-agent-workspace-audit-v1', 'forward-only-g10-agent-workspace-audit-v1', UTC_TIMESTAMP(3));
