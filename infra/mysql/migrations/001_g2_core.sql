-- G2 forward-only schema. Every object is created without removing or
-- rewriting an existing object. The migration runner rejects destructive SQL.

CREATE TABLE IF NOT EXISTS recpro_schema_migration (
    migration_id VARCHAR(128) NOT NULL,
    migration_checksum CHAR(64) NOT NULL,
    applied_at DATETIME(3) NOT NULL,
    PRIMARY KEY (migration_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS resource_catalog (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    resource_type VARCHAR(16) NOT NULL,
    external_id VARCHAR(128) NOT NULL,
    title VARCHAR(500) NOT NULL,
    authors_json JSON NOT NULL,
    abstract_text TEXT NULL,
    keywords_json JSON NULL,
    category_code VARCHAR(64) NULL,
    publication_year SMALLINT NULL,
    publication_date DATE NULL,
    publisher_or_source VARCHAR(500) NULL,
    language VARCHAR(16) NULL,
    difficulty_level TINYINT NULL,
    availability_status VARCHAR(24) NOT NULL,
    available_from DATETIME(3) NOT NULL,
    access_url VARCHAR(1000) NULL,
    metadata_quality DECIMAL(7,6) NOT NULL,
    is_classic BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_version INT UNSIGNED NOT NULL DEFAULT 1,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_resource_catalog_external (resource_type, external_id),
    KEY ix_resource_catalog_type_year (resource_type, publication_year),
    KEY ix_resource_catalog_category (category_code),
    KEY ix_resource_catalog_available (available_from),
    CONSTRAINT chk_resource_catalog_type CHECK (resource_type IN ('BOOK','PAPER')),
    CONSTRAINT chk_resource_catalog_quality CHECK (metadata_quality >= 0 AND metadata_quality <= 1),
    CONSTRAINT chk_resource_catalog_difficulty CHECK (difficulty_level IS NULL OR difficulty_level BETWEEN 1 AND 4),
    CONSTRAINT chk_resource_catalog_status CHECK (availability_status IN ('AVAILABLE_BORROW','AVAILABLE_ONLINE','REFERENCE_ONLY','TEMPORARILY_UNAVAILABLE','REMOVED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS resource_book_detail (
    resource_id BIGINT UNSIGNED NOT NULL,
    isbn VARCHAR(32) NULL,
    call_number VARCHAR(128) NULL,
    location VARCHAR(255) NULL,
    borrowable_copies INT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (resource_id),
    CONSTRAINT fk_book_detail_resource FOREIGN KEY (resource_id) REFERENCES resource_catalog (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_book_detail_copies CHECK (borrowable_copies >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS resource_paper_detail (
    resource_id BIGINT UNSIGNED NOT NULL,
    doi VARCHAR(255) NULL,
    journal_or_conference VARCHAR(500) NULL,
    open_access BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (resource_id),
    CONSTRAINT fk_paper_detail_resource FOREIGN KEY (resource_id) REFERENCES resource_catalog (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS tag_dictionary (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    normalized_name VARCHAR(128) NOT NULL,
    parent_id BIGINT UNSIGNED NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_tag_dictionary_normalized (normalized_name),
    KEY ix_tag_dictionary_parent (parent_id),
    CONSTRAINT fk_tag_dictionary_parent FOREIGN KEY (parent_id) REFERENCES tag_dictionary (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_tag_dictionary_status CHECK (status IN ('ACTIVE','INACTIVE'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS resource_tag (
    resource_id BIGINT UNSIGNED NOT NULL,
    tag_id BIGINT UNSIGNED NOT NULL,
    weight DECIMAL(7,6) NOT NULL,
    confidence DECIMAL(7,6) NOT NULL,
    source VARCHAR(24) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (resource_id, tag_id, source),
    KEY ix_resource_tag_tag_weight (tag_id, weight),
    CONSTRAINT fk_resource_tag_resource FOREIGN KEY (resource_id) REFERENCES resource_catalog (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_resource_tag_tag FOREIGN KEY (tag_id) REFERENCES tag_dictionary (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_resource_tag_weight CHECK (weight >= 0 AND weight <= 1),
    CONSTRAINT chk_resource_tag_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT chk_resource_tag_source CHECK (source IN ('HUMAN','RULE','LLM','IMPORT'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS resource_index_state (
    resource_id BIGINT UNSIGNED NOT NULL,
    content_hash CHAR(64) NOT NULL,
    embedding_id VARCHAR(128) NULL,
    embedding_version VARCHAR(64) NULL,
    embedding_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    graph_version VARCHAR(64) NULL,
    graph_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    last_indexed_at DATETIME(3) NULL,
    last_error VARCHAR(1000) NULL,
    PRIMARY KEY (resource_id),
    CONSTRAINT fk_resource_index_state_resource FOREIGN KEY (resource_id) REFERENCES resource_catalog (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_resource_index_state_embedding CHECK (embedding_status IN ('PENDING','READY','STALE','FAILED','SKIPPED')),
    CONSTRAINT chk_resource_index_state_graph CHECK (graph_status IN ('PENDING','READY','STALE','FAILED','SKIPPED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS resource_index_build (
    id CHAR(36) NOT NULL,
    resource_id BIGINT UNSIGNED NOT NULL,
    target VARCHAR(16) NOT NULL,
    index_version VARCHAR(64) NOT NULL,
    metadata_version INT UNSIGNED NOT NULL,
    content_hash CHAR(64) NOT NULL,
    namespace_name VARCHAR(255) NOT NULL,
    status VARCHAR(16) NOT NULL,
    error_code VARCHAR(64) NULL,
    error_detail VARCHAR(1000) NULL,
    started_at DATETIME(3) NULL,
    finished_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL,
    state_version INT UNSIGNED NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    KEY ix_resource_index_build_resource (resource_id, created_at),
    CONSTRAINT fk_resource_index_build_resource FOREIGN KEY (resource_id) REFERENCES resource_catalog (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_resource_index_build_target CHECK (target IN ('VECTOR','GRAPH')),
    CONSTRAINT chk_resource_index_build_status CHECK (status IN ('PLANNED','BUILDING','READY','FAILED','NOT_ACTIVE'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS resource_index_outbox (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    resource_id BIGINT UNSIGNED NOT NULL,
    target VARCHAR(16) NOT NULL,
    operation VARCHAR(16) NOT NULL,
    metadata_version INT UNSIGNED NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    next_retry_at DATETIME(3) NULL,
    locked_at DATETIME(3) NULL,
    locked_by VARCHAR(64) NULL,
    last_error VARCHAR(1000) NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_resource_index_outbox_target (resource_id, target, operation, metadata_version),
    KEY ix_resource_index_outbox_ready (status, next_retry_at),
    CONSTRAINT fk_resource_index_outbox_resource FOREIGN KEY (resource_id) REFERENCES resource_catalog (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_resource_index_outbox_target CHECK (target IN ('VECTOR','GRAPH')),
    CONSTRAINT chk_resource_index_outbox_operation CHECK (operation IN ('UPSERT','DEACTIVATE','REBUILD')),
    CONSTRAINT chk_resource_index_outbox_status CHECK (status IN ('PENDING','PROCESSING','DONE','DEAD'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_behavior_event (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    event_uuid CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    session_id CHAR(36) NOT NULL,
    task_id CHAR(36) NULL,
    event_type VARCHAR(40) NOT NULL,
    resource_id BIGINT UNSIGNED NULL,
    recommendation_item_id BIGINT UNSIGNED NULL,
    impression_uuid CHAR(36) NULL,
    query_text VARCHAR(1000) NULL,
    rating DECIMAL(2,1) NULL,
    dwell_ms INT UNSIGNED NULL,
    visible_ratio DECIMAL(4,3) NULL,
    position SMALLINT UNSIGNED NULL,
    reason_code VARCHAR(40) NULL,
    tag_evidence_json JSON NULL,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_behavior_event_uuid (event_uuid),
    KEY ix_behavior_user_time (user_id, occurred_at),
    KEY ix_behavior_resource_time (resource_id, occurred_at),
    KEY ix_behavior_task (task_id),
    KEY ix_behavior_impression (impression_uuid),
    CONSTRAINT fk_behavior_resource FOREIGN KEY (resource_id) REFERENCES resource_catalog (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_behavior_event_type CHECK (event_type IN ('SEARCH','VIEW_RESOURCE','VIEW_EXPLANATION','CLICK_RECOMMENDATION','FAVORITE_RESOURCE','BORROW_BOOK','ACCESS_PAPER_FULLTEXT','RATE_HIGH','RATE_NEUTRAL','RATE_LOW','REJECT_RECOMMENDATION','NOT_INTERESTED','RECOMMENDATION_IMPRESSION')),
    CONSTRAINT chk_behavior_rating CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5)),
    CONSTRAINT chk_behavior_visible CHECK (visible_ratio IS NULL OR (visible_ratio >= 0 AND visible_ratio <= 1)),
    CONSTRAINT chk_behavior_position CHECK (position IS NULL OR position > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_declared_profile (
    user_id BIGINT UNSIGNED NOT NULL,
    declared_version INT UNSIGNED NOT NULL,
    major VARCHAR(128) NULL,
    grade VARCHAR(32) NULL,
    research_direction VARCHAR(255) NULL,
    preferred_language VARCHAR(32) NULL,
    personalization_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (user_id),
    CONSTRAINT chk_declared_profile_version CHECK (declared_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_declared_profile_history (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    declared_version INT UNSIGNED NOT NULL,
    major VARCHAR(128) NULL,
    grade VARCHAR(32) NULL,
    research_direction VARCHAR(255) NULL,
    preferred_language VARCHAR(32) NULL,
    personalization_enabled BOOLEAN NOT NULL,
    valid_from DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_declared_profile_history_version (user_id, declared_version),
    KEY ix_declared_profile_history_time (user_id, valid_from),
    CONSTRAINT chk_declared_profile_history_version CHECK (declared_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_profile (
    user_id BIGINT UNSIGNED NOT NULL,
    profile_version INT UNSIGNED NOT NULL,
    profile_confidence DECIMAL(7,6) NOT NULL,
    recent_focus_tag_id BIGINT UNSIGNED NULL,
    topic_focus_strength DECIMAL(7,6) NOT NULL,
    reading_stage VARCHAR(16) NULL,
    reading_stage_confidence DECIMAL(7,6) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (user_id),
    KEY ix_user_profile_focus (recent_focus_tag_id),
    CONSTRAINT fk_user_profile_focus_tag FOREIGN KEY (recent_focus_tag_id) REFERENCES tag_dictionary (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_user_profile_confidence CHECK (profile_confidence >= 0 AND profile_confidence <= 1),
    CONSTRAINT chk_user_profile_topic_strength CHECK (topic_focus_strength >= 0 AND topic_focus_strength <= 1),
    CONSTRAINT chk_user_profile_stage CHECK (reading_stage IS NULL OR reading_stage IN ('BEGINNER','INTERMEDIATE','ADVANCED','RESEARCH')),
    CONSTRAINT chk_user_profile_stage_confidence CHECK (reading_stage_confidence >= 0 AND reading_stage_confidence <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_interest_tag (
    user_id BIGINT UNSIGNED NOT NULL,
    tag_id BIGINT UNSIGNED NOT NULL,
    positive_weight DECIMAL(7,6) NOT NULL,
    raw_positive_signal DECIMAL(12,6) NOT NULL,
    source_count INT UNSIGNED NOT NULL,
    last_event_at DATETIME(3) NOT NULL,
    profile_version INT UNSIGNED NOT NULL,
    PRIMARY KEY (user_id, tag_id),
    CONSTRAINT fk_user_interest_tag_tag FOREIGN KEY (tag_id) REFERENCES tag_dictionary (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_user_interest_weight CHECK (positive_weight >= 0 AND positive_weight <= 1),
    CONSTRAINT chk_user_interest_raw CHECK (raw_positive_signal >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_negative_preference (
    user_id BIGINT UNSIGNED NOT NULL,
    tag_id BIGINT UNSIGNED NOT NULL,
    reason_code VARCHAR(40) NOT NULL,
    negative_weight DECIMAL(7,6) NOT NULL,
    raw_negative_signal DECIMAL(12,6) NOT NULL,
    source_count INT UNSIGNED NOT NULL,
    expires_at DATETIME(3) NULL,
    last_event_at DATETIME(3) NOT NULL,
    profile_version INT UNSIGNED NOT NULL,
    PRIMARY KEY (user_id, tag_id, reason_code),
    CONSTRAINT fk_user_negative_tag FOREIGN KEY (tag_id) REFERENCES tag_dictionary (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_user_negative_reason CHECK (reason_code = 'TOPIC_NOT_INTERESTED'),
    CONSTRAINT chk_user_negative_weight CHECK (negative_weight >= 0 AND negative_weight <= 1),
    CONSTRAINT chk_user_negative_raw CHECK (raw_negative_signal >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS profile_change_log (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    source_event_id BIGINT UNSIGNED NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    profile_version_before INT UNSIGNED NOT NULL,
    profile_version_after INT UNSIGNED NOT NULL,
    delta_json JSON NOT NULL,
    formula_version VARCHAR(64) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_profile_change_source (source_event_id, source_type, formula_version),
    KEY ix_profile_change_user (user_id, created_at),
    CONSTRAINT chk_profile_change_version CHECK (profile_version_after > profile_version_before)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS profile_update_outbox (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    source_event_id BIGINT UNSIGNED NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    payload_json JSON NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    next_retry_at DATETIME(3) NULL,
    locked_at DATETIME(3) NULL,
    locked_by VARCHAR(64) NULL,
    last_error VARCHAR(1000) NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_profile_outbox_source (source_event_id, source_type),
    KEY ix_profile_outbox_ready (status, next_retry_at),
    CONSTRAINT chk_profile_outbox_status CHECK (status IN ('PENDING','PROCESSING','DONE','DEAD'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS profile_replay_run (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    as_of DATETIME(3) NOT NULL,
    formula_version VARCHAR(64) NOT NULL,
    input_hash CHAR(64) NOT NULL,
    profile_version INT UNSIGNED NOT NULL,
    event_count INT UNSIGNED NOT NULL,
    applied_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_profile_replay_identity (user_id, as_of, formula_version, input_hash),
    KEY ix_profile_replay_user_time (user_id, as_of)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_config_version (
    config_bundle_version VARCHAR(64) NOT NULL,
    policy_version VARCHAR(64) NOT NULL,
    ranking_version VARCHAR(64) NOT NULL,
    behavior_formula_version VARCHAR(64) NOT NULL,
    prompt_version VARCHAR(64) NOT NULL,
    bundle_json JSON NOT NULL,
    config_hash CHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (config_bundle_version),
    KEY ix_config_status (status, created_at),
    CONSTRAINT chk_config_status CHECK (status IN ('DRAFT','ACTIVE','INACTIVE','REJECTED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS g2_seed_run (
    seed_version VARCHAR(64) NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    resource_count INT UNSIGNED NOT NULL,
    tag_count INT UNSIGNED NOT NULL,
    behavior_count INT UNSIGNED NOT NULL,
    applied_at DATETIME(3) NOT NULL,
    PRIMARY KEY (seed_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g2-core-v1', 'forward-only-g2-schema-v1', UTC_TIMESTAMP(3));
