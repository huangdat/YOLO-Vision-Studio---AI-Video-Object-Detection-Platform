CREATE TABLE detection_jobs (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    model_id UUID NOT NULL,
    video_url TEXT NOT NULL,
    confidence NUMERIC(4,3) NOT NULL,
    image_size INTEGER NOT NULL,
    selected_classes JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    progress INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_detection_jobs PRIMARY KEY (id),
    CONSTRAINT fk_detection_jobs_model FOREIGN KEY (model_id)
        REFERENCES model_configs (id) ON DELETE RESTRICT,
    CONSTRAINT ck_detection_jobs_confidence CHECK (confidence BETWEEN 0.000 AND 1.000),
    CONSTRAINT ck_detection_jobs_progress CHECK (progress BETWEEN 0 AND 100),
    CONSTRAINT ck_detection_jobs_image_size CHECK (image_size > 0),
    CONSTRAINT ck_detection_jobs_status CHECK (status IN (
        'PENDING', 'QUEUED', 'DOWNLOADING', 'DETECTING', 'ENCODING',
        'UPLOADING', 'COMPLETED', 'FAILED', 'CANCELLED'
    )),
    CONSTRAINT ck_detection_jobs_selected_classes_array
        CHECK (jsonb_typeof(selected_classes) = 'array')
);

CREATE INDEX idx_detection_jobs_status ON detection_jobs (status);
CREATE INDEX idx_detection_jobs_created_at ON detection_jobs (created_at DESC, id DESC);
CREATE INDEX idx_detection_jobs_model_id ON detection_jobs (model_id);
CREATE INDEX idx_detection_jobs_status_created_at
    ON detection_jobs (status, created_at DESC, id DESC);
