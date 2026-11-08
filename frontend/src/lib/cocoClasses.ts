/**
 * COCO class IDs of the supported pretrained detection checkpoints (YOLOv8, YOLO11,
 * YOLO12, YOLO26). Copied from the `names` of the real yolo11n.pt and yolo26s.pt
 * checkpoints loaded with Ultralytics 8.4.207 (identical 80-entry maps, IDs 0-79).
 * The backend has no class-catalog endpoint; this is the single frontend source.
 * Custom models with other class sets are not supported in this phase.
 */
export interface DetectionClass {
  id: number;
  name: string;
}

const NAMES = [
  "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
  "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
  "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
  "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
  "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
  "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
  "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
  "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
  "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors",
  "teddy bear", "hair drier", "toothbrush",
] as const;

/** Index in this list is the model's class ID. */
export const COCO_CLASSES: readonly DetectionClass[] = NAMES.map((name, id) => ({ id, name }));

/** Engine default (backend DEFAULT_CLASSES): bicycle, car, motorcycle, bus, truck. */
export const VEHICLE_CLASS_IDS: readonly number[] = [1, 2, 3, 5, 7];

export const ALL_CLASS_IDS: readonly number[] = COCO_CLASSES.map((item) => item.id);

const BY_ID = new Map(COCO_CLASSES.map((item) => [item.id, item.name]));

export function className(id: number): string {
  return BY_ID.get(id) ?? `class ${id}`;
}

export function isKnownClass(id: number): boolean {
  return BY_ID.has(id);
}
