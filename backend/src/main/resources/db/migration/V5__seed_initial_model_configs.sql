-- Metadata registration is not model installation or worker availability.
INSERT INTO model_configs (
    model_key, version, model_size, task_type, weights_filename, enabled
) VALUES (
    'yolo26s', 'YOLO26', 's', 'DETECT', 'yolo26s.pt', FALSE
);
