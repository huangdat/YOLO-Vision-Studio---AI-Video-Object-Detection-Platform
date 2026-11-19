-- Per-job inference precision (Phase 3 of the INT8 quantization work). Additive only.

-- Requested precision. Every existing job, and every request without the field, is FP32.
ALTER TABLE detection_jobs
    ADD COLUMN inference_precision VARCHAR(8) NOT NULL DEFAULT 'FP32',
    ADD CONSTRAINT ck_detection_jobs_inference_precision
        CHECK (inference_precision IN ('FP32', 'INT8'));

-- What the worker actually ran. NULL for results stored before the worker reported it.
ALTER TABLE detection_results
    ADD COLUMN effective_precision VARCHAR(8),
    ADD COLUMN inference_runtime VARCHAR(16),
    ADD CONSTRAINT ck_detection_results_effective_precision
        CHECK (effective_precision IS NULL OR effective_precision IN ('FP32', 'INT8')),
    ADD CONSTRAINT ck_detection_results_inference_runtime
        CHECK (inference_runtime IS NULL OR inference_runtime IN ('PYTORCH', 'OPENVINO'));
