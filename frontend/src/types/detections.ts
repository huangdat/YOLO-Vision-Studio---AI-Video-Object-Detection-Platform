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
