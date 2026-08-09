-- G5 forward-only exposure, feedback, and resource-state facts.
-- Every change is append-first or a controlled current-projection update, with no
-- statement removes an existing fact or object.

CREATE TABLE IF NOT EXISTS recommendation_impression (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    impression_uuid CHAR(36) NOT NULL,
    recommendation_item_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    position SMALLINT UNSIGNED NOT NULL,
    rendered_at DATETIME(3) NOT NULL,
    visible_started_at DATETIME(3) NULL,
    visible_ms INT UNSIGNED NOT NULL DEFAULT 0,
    max_visible_ratio DECIMAL(4,3) NOT NULL DEFAULT 0,
    is_valid_exposure BOOLEAN NOT NULL DEFAULT FALSE,
    clicked_at DATETIME(3) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_impression_uuid (impression_uuid),
    KEY ix_recommendation_impression_user_time (user_id, rendered_at),
    KEY ix_recommendation_impression_item (recommendation_item_id, rendered_at),
    CONSTRAINT fk_recommendation_impression_item FOREIGN KEY (recommendation_item_id) REFERENCES recommendation_item (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_impression_position CHECK (position > 0),
    CONSTRAINT chk_recommendation_impression_visible_ms CHECK (visible_ms >= 0),
    CONSTRAINT chk_recommendation_impression_ratio CHECK (max_visible_ratio >= 0 AND max_visible_ratio <= 1),
    CONSTRAINT chk_recommendation_impression_visible_start CHECK (visible_ms = 0 OR visible_started_at IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS recommendation_feedback (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    feedback_uuid CHAR(36) NOT NULL,
    recommendation_item_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    impression_uuid CHAR(36) NULL,
    feedback_type VARCHAR(32) NOT NULL,
    reason_code VARCHAR(40) NULL,
    rating DECIMAL(2,1) NULL,
    content VARCHAR(1000) NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recommendation_feedback_uuid (feedback_uuid),
    KEY ix_recommendation_feedback_impression (impression_uuid),
    KEY ix_recommendation_feedback_item (recommendation_item_id, created_at),
    CONSTRAINT fk_recommendation_feedback_item FOREIGN KEY (recommendation_item_id) REFERENCES recommendation_item (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_recommendation_feedback_type CHECK (feedback_type IN ('FAVORITE','BORROW','REJECT','NOT_INTERESTED','RATE')),
    CONSTRAINT chk_recommendation_feedback_rating CHECK ((feedback_type = 'RATE' AND rating IS NOT NULL AND rating >= 1 AND rating <= 5) OR (feedback_type <> 'RATE' AND rating IS NULL)),
    CONSTRAINT chk_recommendation_feedback_reason CHECK (reason_code IS NULL OR reason_code IN ('TOPIC_NOT_INTERESTED','ALREADY_READ','TOO_BASIC','TOO_ADVANCED','LOW_QUALITY','NOT_NOW','REPEATED','OTHER'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_resource_state (
    user_id BIGINT UNSIGNED NOT NULL,
    resource_id BIGINT UNSIGNED NOT NULL,
    state_type VARCHAR(32) NOT NULL,
    suppress_until DATETIME(3) NULL,
    source_event_id BIGINT UNSIGNED NOT NULL,
    last_feedback_at DATETIME(3) NOT NULL,
    state_version INT UNSIGNED NOT NULL,
    PRIMARY KEY (user_id, resource_id, state_type),
    KEY ix_user_resource_state_active (user_id, suppress_until),
    CONSTRAINT fk_user_resource_state_resource FOREIGN KEY (resource_id) REFERENCES resource_catalog (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_user_resource_state_event FOREIGN KEY (source_event_id) REFERENCES user_behavior_event (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_user_resource_state_type CHECK (state_type IN ('READ','FAVORITED','BORROWED','HIDDEN','NOT_NOW','DUPLICATE_SUPPRESS')),
    CONSTRAINT chk_user_resource_state_version CHECK (state_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO recpro_schema_migration (migration_id, migration_checksum, applied_at)
VALUES ('g5-feedback-state-v1', 'forward-only-g5-feedback-state-v1', UTC_TIMESTAMP(3));
