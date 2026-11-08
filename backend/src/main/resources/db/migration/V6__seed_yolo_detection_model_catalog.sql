-- Register the approved pretrained Ultralytics detection checkpoints.
--
-- Catalog registration is not enablement, caching, or runtime verification:
-- every new row is disabled until an administrator enables it after the worker
-- runtime has prepared and verified the checkpoint (docs/yolo-model-management.md).
--
-- ON CONFLICT DO NOTHING preserves existing rows exactly, including the V5
-- yolo26s UUID, its enabled flag, timestamps, administrator changes, and any
-- detection_jobs foreign keys. Keep this list in sync with
-- ai-worker/app/services/model_registry.py (enforced by tests/test_model_registry.py).
INSERT INTO model_configs (model_key, version, model_size, task_type, weights_filename, enabled)
VALUES
    ('yolov8n', 'YOLOv8', 'n', 'DETECT', 'yolov8n.pt', FALSE),
    ('yolov8s', 'YOLOv8', 's', 'DETECT', 'yolov8s.pt', FALSE),
    ('yolov8m', 'YOLOv8', 'm', 'DETECT', 'yolov8m.pt', FALSE),
    ('yolov8l', 'YOLOv8', 'l', 'DETECT', 'yolov8l.pt', FALSE),
    ('yolov8x', 'YOLOv8', 'x', 'DETECT', 'yolov8x.pt', FALSE),
    ('yolo11n', 'YOLO11', 'n', 'DETECT', 'yolo11n.pt', FALSE),
    ('yolo11s', 'YOLO11', 's', 'DETECT', 'yolo11s.pt', FALSE),
    ('yolo11m', 'YOLO11', 'm', 'DETECT', 'yolo11m.pt', FALSE),
    ('yolo11l', 'YOLO11', 'l', 'DETECT', 'yolo11l.pt', FALSE),
    ('yolo11x', 'YOLO11', 'x', 'DETECT', 'yolo11x.pt', FALSE),
    ('yolo12n', 'YOLO12', 'n', 'DETECT', 'yolo12n.pt', FALSE),
    ('yolo12s', 'YOLO12', 's', 'DETECT', 'yolo12s.pt', FALSE),
    ('yolo12m', 'YOLO12', 'm', 'DETECT', 'yolo12m.pt', FALSE),
    ('yolo12l', 'YOLO12', 'l', 'DETECT', 'yolo12l.pt', FALSE),
    ('yolo12x', 'YOLO12', 'x', 'DETECT', 'yolo12x.pt', FALSE),
    ('yolo26n', 'YOLO26', 'n', 'DETECT', 'yolo26n.pt', FALSE),
    ('yolo26s', 'YOLO26', 's', 'DETECT', 'yolo26s.pt', FALSE),
    ('yolo26m', 'YOLO26', 'm', 'DETECT', 'yolo26m.pt', FALSE),
    ('yolo26l', 'YOLO26', 'l', 'DETECT', 'yolo26l.pt', FALSE),
    ('yolo26x', 'YOLO26', 'x', 'DETECT', 'yolo26x.pt', FALSE)
ON CONFLICT (model_key) DO NOTHING;
