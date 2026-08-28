-- G12 append-only librarian knowledge governance schema.
-- No statement deletes, replaces, updates, truncates, drops, or cascades.

CREATE TABLE IF NOT EXISTS knowledge_review_proposal (
    proposal_uuid CHAR(36) NOT NULL,
    proposal_type VARCHAR(40) NOT NULL,
    graph_version VARCHAR(64) NOT NULL,
    subject_id VARCHAR(256) NOT NULL,
    relation_type VARCHAR(64) NOT NULL,
    object_id VARCHAR(256) NOT NULL,
    source_refs_json JSON NOT NULL,
    reason_codes_json JSON NOT NULL,
    confidence DECIMAL(8,6) NOT NULL,
    agent_name VARCHAR(64) NOT NULL,
    task_id CHAR(36) NULL,
    workspace_id CHAR(36) NULL,
    idempotency_sha256 CHAR(64) NOT NULL,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (proposal_uuid),
    UNIQUE KEY uq_knowledge_review_proposal_idempotency (idempotency_sha256),
    KEY ix_knowledge_review_proposal_graph_reason (graph_version, proposal_type, occurred_at),
    KEY ix_knowledge_review_proposal_task (task_id),
    KEY ix_knowledge_review_proposal_workspace (workspace_id),
    CONSTRAINT chk_knowledge_review_proposal_confidence CHECK (confidence >= 0 AND confidence <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS knowledge_review_action_fact (
    fact_uuid CHAR(36) NOT NULL,
    proposal_uuid CHAR(36) NOT NULL,
    action_version INT UNSIGNED NOT NULL,
    action VARCHAR(24) NOT NULL,
    librarian_user_id BIGINT UNSIGNED NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (fact_uuid),
    UNIQUE KEY uq_knowledge_review_action_version (proposal_uuid, action_version),
    UNIQUE KEY uq_knowledge_review_action_idempotency (idempotency_key),
    KEY ix_knowledge_review_action_actor (librarian_user_id, occurred_at),
    CONSTRAINT fk_knowledge_review_action_proposal FOREIGN KEY (proposal_uuid) REFERENCES knowledge_review_proposal (proposal_uuid) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_knowledge_review_action_librarian FOREIGN KEY (librarian_user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_knowledge_review_action CHECK (action IN ('APPROVE','REJECT','REQUEST_EVIDENCE')),
    CONSTRAINT chk_knowledge_review_action_version CHECK (action_version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE VIEW knowledge_review_current_v AS
SELECT p.proposal_uuid, p.proposal_type, p.graph_version, p.subject_id,
       p.relation_type, p.object_id, p.confidence, p.agent_name,
       CASE latest.action
           WHEN 'APPROVE' THEN 'APPROVED'
           WHEN 'REJECT' THEN 'REJECTED'
           WHEN 'REQUEST_EVIDENCE' THEN 'EVIDENCE_REQUESTED'
           ELSE 'PENDING'
       END AS current_status,
       latest.action_version, latest.librarian_user_id,
       latest.reason_code AS latest_reason_code,
       latest.occurred_at AS latest_action_at,
       p.occurred_at AS proposed_at
FROM knowledge_review_proposal AS p
LEFT JOIN knowledge_review_action_fact AS latest
  ON latest.proposal_uuid = p.proposal_uuid
 AND latest.action_version = (
    SELECT MAX(candidate.action_version)
    FROM knowledge_review_action_fact AS candidate
    WHERE candidate.proposal_uuid = p.proposal_uuid
 );

INSERT IGNORE INTO iam_permission (
    permission_id, permission_code, description, resource_scope, created_at
) VALUES (
    16, 'catalog.knowledge.review', '审核知识图谱冲突与证据提案', 'LIBRARY', '2026-08-28 00:00:00.000'
);

INSERT IGNORE INTO iam_role_permission_fact (
    fact_uuid, role_id, permission_id, permission_version, action,
    actor_user_id, reason_code, idempotency_key, occurred_at, created_at
) VALUES
    ('3d3ca04a-d365-5961-af95-8c9dc850dd2d', 2, 16, 1, 'GRANT', NULL, 'G12_FIXED_SEED', 'g12:role:librarian:catalog.knowledge.review:v1', '2026-08-28 00:00:00.000', '2026-08-28 00:00:00.000'),
    ('8d05cdbb-7dac-5dd7-bf90-4866b05e2ea5', 3, 16, 1, 'GRANT', NULL, 'G12_FIXED_SEED', 'g12:role:research_admin:catalog.knowledge.review:v1', '2026-08-28 00:00:00.000', '2026-08-28 00:00:00.000');

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g12-knowledge-review-v1', 'b1f5bd6302d307f39cdf822a39266e8577337cc7ea9f915aa3eeebf863ff1c92', UTC_TIMESTAMP(3));
