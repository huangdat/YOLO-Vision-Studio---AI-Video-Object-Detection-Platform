export const DETECTION_JOB_STATUSES = [
  "PENDING",
  "QUEUED",
  "DOWNLOADING",
  "DETECTING",
  "ENCODING",
  "UPLOADING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
] as const;

export type DetectionJobStatus = (typeof DETECTION_JOB_STATUSES)[number];

export type DetectionSourceType = "YOUTUBE_URL" | "LOCAL_FILE";

/**
 * DETECTION_ONLY analyses frames independently. DETECTION_TRACKING also runs ByteTrack in the
 * worker, so detections keep a Track ID within the job. Missing in legacy data: Detection Only.
 */
export type ProcessingMode = "DETECTION_ONLY" | "DETECTION_TRACKING";

/** Requested per-job inference precision. FP32 is the default; INT8 is opt-in and experimental. */
export type InferencePrecision = "FP32" | "INT8";

/** Runtime the worker actually used, as reported in the job result. */
export type InferenceRuntime = "PYTORCH" | "OPENVINO";

/** DetectionJobDetailsResponse (GET /detections/{jobId}). */
export interface DetectionJob {
  jobId: string;
  modelKey: string;
  modelVersion: string;
  sourceType: DetectionSourceType;
  /** Only present for YouTube sources. */
  videoUrl: string | null;
  status: DetectionJobStatus;
  progress: number;
  confidence: number;
  imageSize: number;
  classes: number[];
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  updatedAt: string;
  errorCode: string | null;
  errorMessage: string | null;
  processingMode: ProcessingMode;
  /** Requested precision; null only from backends without precision support. */
  inferencePrecision: InferencePrecision | null;
}

/** DetectionJobSummaryResponse (one row of GET /detections). */
export interface DetectionJobSummary {
  jobId: string;
  modelKey: string;
  status: DetectionJobStatus;
  progress: number;
  createdAt: string;
  completedAt: string | null;
  errorCode: string | null;
  processingMode: ProcessingMode;
  inferencePrecision: InferencePrecision | null;
}

export interface DetectionHistoryQuery {
  page?: number;
  size?: number;
  status?: DetectionJobStatus;
  modelKey?: string;
}

/**
 * DetectionResultMetadataResponse. Counts are bounding-box detections summed over all
 * processed frames (countSemantics), not unique objects.
 */
export interface DetectionResultMetadata {
  jobId: string;
  status: DetectionJobStatus;
  modelKey: string;
  modelVersion: string;
  totalFrames: number | null;
  totalDetections: number;
  processingTimeMs: number | null;
  detectionSummary: Record<string, number>;
  countSemantics: string;
  outputVideoAvailable: boolean;
  resultMetadataAvailable: boolean;
  createdAt: string;
  completedAt: string | null;
  processingMode: ProcessingMode;
  /** Only for tracking jobs whose worker reported tracking totals. */
  tracking: TrackingSummary | null;
  /** What the worker actually ran; null for results stored before workers reported it. */
  effectivePrecision: InferencePrecision | null;
  inferenceRuntime: InferenceRuntime | null;
}

/**
 * ByteTrack totals of a tracking job. `uniqueTrackIds` counts the IDs assigned within the job;
 * ID switches and fragmentation mean it is not guaranteed to equal the number of physical objects.
 */
export interface TrackingSummary {
  tracker: string;
  uniqueTrackIds: number;
  maxActiveTracks: number;
  trackedDetections: number;
  uniqueTrackIdsByClass: Record<string, number>;
  countSemantics: string;
}

/** Payload of the SSE events detection.progress/completed/failed/cancelled. */
export interface DetectionProgressEvent {
  jobId: string;
  status: DetectionJobStatus;
  progress: number;
  message: string | null;
  errorCode: string | null;
  /** The job's last persisted update time. */
  timestamp: string;
}

/** CreateDetectionRequest (POST /detections). Unknown fields are rejected by the backend. */
export interface CreateDetectionRequest {
  videoUrl: string;
  modelKey: string;
  confidence: number;
  imageSize: number;
  classes: number[];
  processingMode: ProcessingMode;
  inferencePrecision: InferencePrecision;
}

/** DetectionJobAcceptedResponse, returned with HTTP 202 and a Location header. */
export interface DetectionJobAccepted {
  jobId: string;
  status: DetectionJobStatus;
  progress: number;
  modelKey: string;
  message: string;
}
