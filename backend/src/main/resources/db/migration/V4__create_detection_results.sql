CREATE TABLE detection_results (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL,
    input_video_key TEXT,
    output_video_key TEXT NOT NULL,
    total_frames INTEGER,
    processing_time_ms BIGINT,
    detection_summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_detection_results PRIMARY KEY (id),
    CONSTRAINT uk_detection_results_job_id UNIQUE (job_id),
    CONSTRAINT fk_detection_results_job FOREIGN KEY (job_id)
        REFERENCES detection_jobs (id) ON DELETE CASCADE,
    CONSTRAINT ck_detection_results_total_frames CHECK (total_frames >= 0),
    CONSTRAINT ck_detection_results_processing_time_ms CHECK (processing_time_ms >= 0),
    CONSTRAINT ck_detection_results_summary_object
        CHECK (jsonb_typeof(detection_summary) = 'object')
);
