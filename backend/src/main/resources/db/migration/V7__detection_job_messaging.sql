-- Phase 05: asynchronous processing metadata and a transactional outbox.

-- Jobs created before this migration were YouTube requests by definition.
ALTER TABLE detection_jobs
    ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'YOUTUBE_URL',
    ADD COLUMN error_code VARCHAR(64),
    ADD CONSTRAINT ck_detection_jobs_source_type CHECK (source_type IN ('YOUTUBE_URL', 'LOCAL_FILE'));

-- Object-storage key of the uploaded result metadata (output video key already exists).
ALTER TABLE detection_results ADD COLUMN result_json_key TEXT;

-- Messages written in the same transaction as the job they describe. A row is
-- PUBLISHED only after the broker confirmed it; FAILED after bounded attempts.
CREATE TABLE detection_job_outbox (
    id UUID NOT NULL,
    job_id UUID NOT NULL,
    message_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMPTZ,
    CONSTRAINT pk_detection_job_outbox PRIMARY KEY (id),
    CONSTRAINT fk_detection_job_outbox_job FOREIGN KEY (job_id)
        REFERENCES detection_jobs (id) ON DELETE CASCADE,
    CONSTRAINT ck_detection_job_outbox_status CHECK (status IN ('PENDING', 'PUBLISHED', 'FAILED')),
    CONSTRAINT ck_detection_job_outbox_attempts CHECK (attempts >= 0),
    CONSTRAINT ck_detection_job_outbox_payload_object CHECK (jsonb_typeof(payload) = 'object')
);

-- One execution command per job prevents duplicate publication requests.
CREATE UNIQUE INDEX uk_detection_job_outbox_job_message_type
    ON detection_job_outbox (job_id, message_type);
CREATE INDEX idx_detection_job_outbox_due
    ON detection_job_outbox (next_attempt_at) WHERE status = 'PENDING';
