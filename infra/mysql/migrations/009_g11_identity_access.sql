-- G11 forward-only local identity and access schema.
-- Creates new objects and fixed authorization seeds only. It never removes,
-- rewrites, replaces, or cascades deletion of an existing fact.

CREATE TABLE IF NOT EXISTS iam_user_account (
    user_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    account_uuid CHAR(36) NOT NULL,
    display_name VARCHAR(80) NOT NULL,
    account_kind VARCHAR(16) NOT NULL,
    status VARCHAR(24) NOT NULL,
    auth_version INT UNSIGNED NOT NULL DEFAULT 1,
    role_version INT UNSIGNED NOT NULL DEFAULT 1,
    must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
    failed_login_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    locked_until DATETIME(3) NULL,
    last_login_at DATETIME(3) NULL,
    disabled_reason VARCHAR(64) NULL,
    created_by_user_id BIGINT UNSIGNED NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_iam_user_account_uuid (account_uuid),
    KEY ix_iam_user_account_status (status, updated_at),
    KEY ix_iam_user_account_creator (created_by_user_id),
    CONSTRAINT fk_iam_user_account_creator FOREIGN KEY (created_by_user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_iam_user_account_kind CHECK (account_kind IN ('HUMAN','SERVICE')),
    CONSTRAINT chk_iam_user_account_status CHECK (status IN ('PENDING_ACTIVATION','ACTIVE','DISABLED')),
    CONSTRAINT chk_iam_user_account_versions CHECK (auth_version >= 1 AND role_version >= 1)
) ENGINE=InnoDB AUTO_INCREMENT=10000 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_login_identifier (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    identifier_type VARCHAR(24) NOT NULL,
    identifier_hash BINARY(32) NOT NULL,
    display_suffix VARCHAR(8) NOT NULL,
    normalization_version VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    disabled_at DATETIME(3) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_iam_login_identifier_hash (identifier_hash),
    KEY ix_iam_login_identifier_user (user_id, status),
    CONSTRAINT fk_iam_login_identifier_user FOREIGN KEY (user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_iam_login_identifier_type CHECK (identifier_type IN ('READER_NUMBER','STUDENT_NUMBER')),
    CONSTRAINT chk_iam_login_identifier_status CHECK (status IN ('ACTIVE','DISABLED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_password_credential (
    user_id BIGINT UNSIGNED NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    algorithm VARCHAR(16) NOT NULL,
    parameters_version VARCHAR(32) NOT NULL,
    password_version INT UNSIGNED NOT NULL,
    changed_at DATETIME(3) NOT NULL,
    expires_at DATETIME(3) NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (user_id),
    CONSTRAINT fk_iam_password_credential_user FOREIGN KEY (user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_iam_password_algorithm CHECK (algorithm = 'ARGON2ID'),
    CONSTRAINT chk_iam_password_version CHECK (password_version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_role (
    role_id SMALLINT UNSIGNED NOT NULL,
    role_code VARCHAR(32) NOT NULL,
    role_name VARCHAR(64) NOT NULL,
    description VARCHAR(255) NOT NULL,
    interactive_login_allowed BOOLEAN NOT NULL,
    system_reserved BOOLEAN NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (role_id),
    UNIQUE KEY uq_iam_role_code (role_code),
    CONSTRAINT chk_iam_role_code CHECK (role_code IN ('user','librarian','research_admin','service_worker'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_permission (
    permission_id SMALLINT UNSIGNED NOT NULL,
    permission_code VARCHAR(64) NOT NULL,
    description VARCHAR(255) NOT NULL,
    resource_scope VARCHAR(32) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (permission_id),
    UNIQUE KEY uq_iam_permission_code (permission_code),
    CONSTRAINT chk_iam_permission_scope CHECK (resource_scope IN ('SELF','LIBRARY','RESEARCH','INTERNAL'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_role_permission_fact (
    fact_uuid CHAR(36) NOT NULL,
    role_id SMALLINT UNSIGNED NOT NULL,
    permission_id SMALLINT UNSIGNED NOT NULL,
    permission_version INT UNSIGNED NOT NULL,
    action VARCHAR(16) NOT NULL,
    actor_user_id BIGINT UNSIGNED NULL,
    reason_code VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (fact_uuid),
    UNIQUE KEY uq_iam_role_permission_version (role_id, permission_id, permission_version),
    UNIQUE KEY uq_iam_role_permission_idempotency (idempotency_key),
    KEY ix_iam_role_permission_latest (role_id, permission_id, permission_version),
    CONSTRAINT fk_iam_role_permission_role FOREIGN KEY (role_id) REFERENCES iam_role (role_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_iam_role_permission_permission FOREIGN KEY (permission_id) REFERENCES iam_permission (permission_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_iam_role_permission_actor FOREIGN KEY (actor_user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_iam_role_permission_action CHECK (action IN ('GRANT','REVOKE')),
    CONSTRAINT chk_iam_role_permission_version CHECK (permission_version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_user_role_fact (
    fact_uuid CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    role_id SMALLINT UNSIGNED NOT NULL,
    role_version INT UNSIGNED NOT NULL,
    action VARCHAR(16) NOT NULL,
    actor_user_id BIGINT UNSIGNED NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (fact_uuid),
    UNIQUE KEY uq_iam_user_role_version (user_id, role_id, role_version),
    UNIQUE KEY uq_iam_user_role_idempotency (idempotency_key),
    KEY ix_iam_user_role_latest (user_id, role_id, role_version),
    CONSTRAINT fk_iam_user_role_user FOREIGN KEY (user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_iam_user_role_role FOREIGN KEY (role_id) REFERENCES iam_role (role_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_iam_user_role_actor FOREIGN KEY (actor_user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_iam_user_role_action CHECK (action IN ('GRANT','REVOKE')),
    CONSTRAINT chk_iam_user_role_version CHECK (role_version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_auth_session (
    session_uuid CHAR(36) NOT NULL,
    token_family_uuid CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    device_type VARCHAR(16) NOT NULL,
    auth_version_at_issue INT UNSIGNED NOT NULL,
    role_version_at_issue INT UNSIGNED NOT NULL,
    csrf_secret_hash BINARY(32) NOT NULL,
    ip_hash BINARY(32) NULL,
    user_agent_hash BINARY(32) NULL,
    issued_at DATETIME(3) NOT NULL,
    absolute_expires_at DATETIME(3) NOT NULL,
    last_seen_at DATETIME(3) NOT NULL,
    revoked_at DATETIME(3) NULL,
    revoke_reason VARCHAR(64) NULL,
    PRIMARY KEY (session_uuid),
    UNIQUE KEY uq_iam_auth_session_family (token_family_uuid),
    KEY ix_iam_auth_session_user (user_id, revoked_at, absolute_expires_at),
    CONSTRAINT fk_iam_auth_session_user FOREIGN KEY (user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_iam_auth_session_device CHECK (device_type IN ('KIOSK','BROWSER')),
    CONSTRAINT chk_iam_auth_session_versions CHECK (auth_version_at_issue >= 1 AND role_version_at_issue >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_refresh_token (
    token_uuid CHAR(36) NOT NULL,
    session_uuid CHAR(36) NOT NULL,
    token_hash BINARY(32) NOT NULL,
    parent_token_uuid CHAR(36) NULL,
    issued_at DATETIME(3) NOT NULL,
    expires_at DATETIME(3) NOT NULL,
    consumed_at DATETIME(3) NULL,
    revoked_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (token_uuid),
    UNIQUE KEY uq_iam_refresh_token_hash (token_hash),
    KEY ix_iam_refresh_token_session (session_uuid, issued_at),
    KEY ix_iam_refresh_token_parent (parent_token_uuid),
    CONSTRAINT fk_iam_refresh_token_session FOREIGN KEY (session_uuid) REFERENCES iam_auth_session (session_uuid) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_iam_refresh_token_parent FOREIGN KEY (parent_token_uuid) REFERENCES iam_refresh_token (token_uuid) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_action_token (
    token_uuid CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    purpose VARCHAR(24) NOT NULL,
    token_hash BINARY(32) NOT NULL,
    issued_by_user_id BIGINT UNSIGNED NOT NULL,
    expires_at DATETIME(3) NOT NULL,
    consumed_at DATETIME(3) NULL,
    revoked_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (token_uuid),
    UNIQUE KEY uq_iam_action_token_hash (token_hash),
    KEY ix_iam_action_token_user_purpose (user_id, purpose, created_at),
    CONSTRAINT fk_iam_action_token_user FOREIGN KEY (user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_iam_action_token_issuer FOREIGN KEY (issued_by_user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_iam_action_token_purpose CHECK (purpose IN ('ACTIVATE_ACCOUNT','RESET_PASSWORD'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS iam_security_event (
    event_uuid CHAR(36) NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    user_id BIGINT UNSIGNED NULL,
    actor_user_id BIGINT UNSIGNED NULL,
    session_uuid CHAR(36) NULL,
    identifier_hash BINARY(32) NULL,
    request_id CHAR(36) NULL,
    reason_code VARCHAR(64) NOT NULL,
    ip_hash BINARY(32) NULL,
    user_agent_hash BINARY(32) NULL,
    metadata_json JSON NULL,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (event_uuid),
    KEY ix_iam_security_event_user_time (user_id, occurred_at),
    KEY ix_iam_security_event_actor_time (actor_user_id, occurred_at),
    KEY ix_iam_security_event_type_time (event_type, occurred_at),
    KEY ix_iam_security_event_session (session_uuid, occurred_at),
    CONSTRAINT fk_iam_security_event_user FOREIGN KEY (user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_iam_security_event_actor FOREIGN KEY (actor_user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_iam_security_event_session FOREIGN KEY (session_uuid) REFERENCES iam_auth_session (session_uuid) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_iam_security_event_outcome CHECK (outcome IN ('SUCCESS','DENIED','FAILED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_personalization_consent_fact (
    consent_uuid CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    scope VARCHAR(40) NOT NULL,
    consent_version INT UNSIGNED NOT NULL,
    action VARCHAR(16) NOT NULL,
    policy_version VARCHAR(64) NOT NULL,
    source VARCHAR(24) NOT NULL,
    evidence_hash CHAR(64) NOT NULL,
    session_uuid CHAR(36) NOT NULL,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (consent_uuid),
    UNIQUE KEY uq_user_consent_version (user_id, scope, consent_version),
    KEY ix_user_consent_latest (user_id, scope, consent_version),
    CONSTRAINT fk_user_consent_user FOREIGN KEY (user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_user_consent_session FOREIGN KEY (session_uuid) REFERENCES iam_auth_session (session_uuid) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_user_consent_scope CHECK (scope IN ('DECLARED_PROFILE','BEHAVIOR_LEARNING','PERSONALIZED_RECOMMENDATION','RESEARCH_ANALYTICS')),
    CONSTRAINT chk_user_consent_action CHECK (action IN ('GRANT','WITHDRAW')),
    CONSTRAINT chk_user_consent_version CHECK (consent_version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE VIEW iam_effective_role_permission_v AS
SELECT f.role_id, f.permission_id, f.action, f.permission_version, f.occurred_at
FROM iam_role_permission_fact AS f
INNER JOIN (
    SELECT role_id, permission_id, MAX(permission_version) AS permission_version
    FROM iam_role_permission_fact
    GROUP BY role_id, permission_id
) AS latest ON latest.role_id = f.role_id
    AND latest.permission_id = f.permission_id
    AND latest.permission_version = f.permission_version
WHERE f.action = 'GRANT';

CREATE VIEW iam_effective_user_role_v AS
SELECT f.user_id, f.role_id, f.action, f.role_version, f.occurred_at
FROM iam_user_role_fact AS f
INNER JOIN (
    SELECT user_id, role_id, MAX(role_version) AS role_version
    FROM iam_user_role_fact
    GROUP BY user_id, role_id
) AS latest ON latest.user_id = f.user_id
    AND latest.role_id = f.role_id
    AND latest.role_version = f.role_version
WHERE f.action = 'GRANT';

CREATE VIEW user_effective_personalization_consent_v AS
SELECT f.user_id, f.scope, f.action, f.consent_version, f.policy_version, f.occurred_at
FROM user_personalization_consent_fact AS f
INNER JOIN (
    SELECT user_id, scope, MAX(consent_version) AS consent_version
    FROM user_personalization_consent_fact
    GROUP BY user_id, scope
) AS latest ON latest.user_id = f.user_id
    AND latest.scope = f.scope
    AND latest.consent_version = f.consent_version;

INSERT IGNORE INTO iam_role (
    role_id, role_code, role_name, description,
    interactive_login_allowed, system_reserved, created_at
) VALUES
    (1, 'user', '读者', '访问自己的推荐、画像与反馈能力', TRUE, TRUE, '2026-08-21 00:00:00.000'),
    (2, 'librarian', '馆员', '管理普通读者账号与密码重置', TRUE, TRUE, '2026-08-21 00:00:00.000'),
    (3, 'research_admin', '研究管理员', '访问论文研究、追踪与角色授权能力', TRUE, TRUE, '2026-08-21 00:00:00.000'),
    (4, 'service_worker', '内部任务身份', '仅供内部画像任务消费，不允许交互登录', FALSE, TRUE, '2026-08-21 00:00:00.000');

INSERT IGNORE INTO iam_permission (
    permission_id, permission_code, description, resource_scope, created_at
) VALUES
    (1, 'catalog.read', '读取馆藏、图谱与资源详情', 'LIBRARY', '2026-08-21 00:00:00.000'),
    (2, 'recommendation.self.execute', '执行自己的推荐和阅读路径', 'SELF', '2026-08-21 00:00:00.000'),
    (3, 'workspace.self.use', '使用自己的 Agent Workspace', 'SELF', '2026-08-21 00:00:00.000'),
    (4, 'profile.self.read', '读取自己的画像', 'SELF', '2026-08-21 00:00:00.000'),
    (5, 'profile.self.update', '更新自己的声明画像', 'SELF', '2026-08-21 00:00:00.000'),
    (6, 'feedback.self.write', '追加自己的反馈与行为事实', 'SELF', '2026-08-21 00:00:00.000'),
    (7, 'account.reader.create', '创建普通读者账号', 'LIBRARY', '2026-08-21 00:00:00.000'),
    (8, 'account.reader.read', '读取普通读者账号状态', 'LIBRARY', '2026-08-21 00:00:00.000'),
    (9, 'account.reader.disable', '禁用或启用普通读者账号', 'LIBRARY', '2026-08-21 00:00:00.000'),
    (10, 'account.reader.reset_password', '签发一次性密码重置码', 'LIBRARY', '2026-08-21 00:00:00.000'),
    (11, 'role.assign', '授予或撤销交互角色', 'RESEARCH', '2026-08-21 00:00:00.000'),
    (12, 'research.trace.read', '读取完整 Agent 研究追踪', 'RESEARCH', '2026-08-21 00:00:00.000'),
    (13, 'research.profile.replay', '执行受控画像重算', 'RESEARCH', '2026-08-21 00:00:00.000'),
    (14, 'research.audit.read', '读取研究审计事实', 'RESEARCH', '2026-08-21 00:00:00.000'),
    (15, 'worker.profile.consume', '消费画像 Outbox', 'INTERNAL', '2026-08-21 00:00:00.000');

INSERT IGNORE INTO iam_role_permission_fact (
    fact_uuid, role_id, permission_id, permission_version, action,
    actor_user_id, reason_code, idempotency_key, occurred_at, created_at
) VALUES
    ('883d40f6-fcba-52ec-819f-c7c39277d33e', 1, 1, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:user:catalog.read:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('b6f390ed-bd2f-5751-bf2b-f3c7007909f9', 1, 2, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:user:recommendation.self.execute:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('65443af6-58d0-5171-966b-5519275c0a34', 1, 3, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:user:workspace.self.use:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('d5de09e4-9027-5fbf-b6e2-17c1573cf529', 1, 4, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:user:profile.self.read:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('09fdaf62-fccc-5034-9675-5daf96e5c7d5', 1, 5, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:user:profile.self.update:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('b3a9fb35-7037-5d7d-9f92-7728fd2856a2', 1, 6, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:user:feedback.self.write:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('26ce919f-1909-562c-9bad-1dfe93867d9f', 2, 1, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:librarian:catalog.read:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('e5e3a2e8-919b-5856-beb8-3175ccb0609c', 2, 7, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:librarian:account.reader.create:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('28b3d991-50f2-5ba3-8a1b-0576cb2201b3', 2, 8, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:librarian:account.reader.read:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('00fa01bc-5815-5256-b1c7-a6493ffbad88', 2, 9, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:librarian:account.reader.disable:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('145f8a1a-74a8-51cb-ae40-76c0e1a66519', 2, 10, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:librarian:account.reader.reset_password:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('503d8378-ebfb-5d35-9d5b-7bccf2afc2e5', 3, 1, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:research_admin:catalog.read:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('ff2b0720-6333-5b90-9b0b-d5fad0657ab0', 3, 11, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:research_admin:role.assign:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('3c97c178-81a1-5828-ad69-c55699c576ea', 3, 12, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:research_admin:research.trace.read:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('90d193cb-45d2-58c8-9fdb-1513a7cc446c', 3, 13, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:research_admin:research.profile.replay:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('46912cbe-4a55-5f33-843d-45ac23590f5a', 3, 14, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:research_admin:research.audit.read:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000'),
    ('c7fb220a-516d-508d-8dd1-ef2e6f2ff438', 4, 15, 1, 'GRANT', NULL, 'G11_FIXED_SEED', 'g11:role:service_worker:worker.profile.consume:v1', '2026-08-21 00:00:00.000', '2026-08-21 00:00:00.000');

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g11-identity-access-v1', 'fdbc2dc04aabb5d3c6516d6a54f2341ad526f77b90304de42b6ec92f883a86c3', UTC_TIMESTAMP(3));
