-- G14 forward-only external OIDC identity binding.
-- Stores no raw external issuer, subject, token, or externally asserted role.
-- The subject is an HMAC-SHA256 digest produced by the application mapper.

CREATE TABLE IF NOT EXISTS iam_oidc_identity_binding (
    binding_uuid CHAR(36) NOT NULL,
    issuer_sha256 BINARY(32) NOT NULL,
    subject_hash BINARY(32) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_by_user_id BIGINT UNSIGNED NULL,
    created_at DATETIME(3) NOT NULL,
    disabled_at DATETIME(3) NULL,
    disabled_reason VARCHAR(64) NULL,
    PRIMARY KEY (binding_uuid),
    UNIQUE KEY uq_iam_oidc_identity_subject (issuer_sha256, subject_hash),
    KEY ix_iam_oidc_identity_user (user_id, status),
    CONSTRAINT fk_iam_oidc_identity_user FOREIGN KEY (user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_iam_oidc_identity_creator FOREIGN KEY (created_by_user_id) REFERENCES iam_user_account (user_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_iam_oidc_identity_status CHECK (status IN ('ACTIVE','DISABLED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g14-oidc-identity-binding-v1', '32d26aae80cbcb756c8e6ad6951f2d760d6de3eb9b61bc75965fab62b057244a', UTC_TIMESTAMP(3));
