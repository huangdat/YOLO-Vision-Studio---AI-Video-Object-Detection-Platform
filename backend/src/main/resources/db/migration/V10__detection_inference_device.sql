-- Device a result was computed on (hybrid tracking and GPU work). Additive and nullable:
-- results stored before workers reported it keep NULL.
ALTER TABLE detection_results
    ADD COLUMN inference_device VARCHAR(16),
    ADD CONSTRAINT ck_detection_results_inference_device
        CHECK (inference_device IS NULL OR inference_device = 'cpu' OR inference_device LIKE 'cuda:%');
