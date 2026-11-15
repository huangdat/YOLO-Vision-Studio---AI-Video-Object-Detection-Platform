-- Object tracking (ByteTrack) as an optional processing mode.

-- Every existing job was processed frame by frame without tracking.
ALTER TABLE detection_jobs
    ADD COLUMN processing_mode VARCHAR(32) NOT NULL DEFAULT 'DETECTION_ONLY',
    ADD CONSTRAINT ck_detection_jobs_processing_mode
        CHECK (processing_mode IN ('DETECTION_ONLY', 'DETECTION_TRACKING'));

-- Compact tracking totals reported by the worker; NULL for detection-only results.
ALTER TABLE detection_results
    ADD COLUMN tracking_summary JSONB,
    ADD CONSTRAINT ck_detection_results_tracking_summary_object
        CHECK (tracking_summary IS NULL OR jsonb_typeof(tracking_summary) = 'object');
