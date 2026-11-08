import { API_BASE_URL, apiClient, request } from "./client";
import {
  array,
  boolean,
  invalid,
  nullableNumber,
  nullableString,
  number,
  record,
  status,
  string,
  type JsonRecord,
} from "./guards";
import type { PageResponse } from "../types/api";
import type {
  CreateDetectionRequest,
  DetectionHistoryQuery,
  DetectionJobAccepted,
  DetectionJob,
  DetectionJobSummary,
  DetectionProgressEvent,
  DetectionResultMetadata,
  DetectionSourceType,
} from "../types/detections";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The backend identifies jobs by UUID; anything else can never match a job. */
export function isJobId(value: string | undefined | null): value is string {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

function toSummary(value: unknown): DetectionJobSummary {
  const data = record(value);
  return {
    jobId: string(data, "jobId"),
    modelKey: string(data, "modelKey"),
    status: status(data),
    progress: number(data, "progress"),
    createdAt: string(data, "createdAt"),
    completedAt: nullableString(data, "completedAt"),
    errorCode: nullableString(data, "errorCode"),
  };
}

export function toDetectionJob(value: unknown): DetectionJob {
  const data = record(value);
  const sourceType = string(data, "sourceType");
  if (sourceType !== "YOUTUBE_URL" && sourceType !== "LOCAL_FILE") invalid();
  return {
    jobId: string(data, "jobId"),
    modelKey: string(data, "modelKey"),
    modelVersion: string(data, "modelVersion"),
    sourceType: sourceType as DetectionSourceType,
    videoUrl: nullableString(data, "videoUrl"),
    status: status(data),
    progress: number(data, "progress"),
    confidence: number(data, "confidence"),
    imageSize: number(data, "imageSize"),
    classes: array(data.classes).map((item) => {
      if (typeof item !== "number") invalid();
      return item;
    }),
    createdAt: string(data, "createdAt"),
    startedAt: nullableString(data, "startedAt"),
    completedAt: nullableString(data, "completedAt"),
    updatedAt: string(data, "updatedAt"),
    errorCode: nullableString(data, "errorCode"),
    errorMessage: nullableString(data, "errorMessage"),
  };
}

function toResult(value: unknown): DetectionResultMetadata {
  const data = record(value);
  const summary: Record<string, number> = {};
  for (const [label, count] of Object.entries(record(data.detectionSummary))) {
    if (typeof count !== "number" || !Number.isFinite(count)) invalid();
    summary[label] = count;
  }
  return {
    jobId: string(data, "jobId"),
    status: status(data),
    modelKey: string(data, "modelKey"),
    modelVersion: string(data, "modelVersion"),
    totalFrames: nullableNumber(data, "totalFrames"),
    totalDetections: number(data, "totalDetections"),
    processingTimeMs: nullableNumber(data, "processingTimeMs"),
    detectionSummary: summary,
    countSemantics: string(data, "countSemantics"),
    outputVideoAvailable: boolean(data, "outputVideoAvailable"),
    resultMetadataAvailable: boolean(data, "resultMetadataAvailable"),
    createdAt: string(data, "createdAt"),
    completedAt: nullableString(data, "completedAt"),
  };
}

/** Parses one SSE data payload; returns null for anything that is not a valid event. */
export function parseProgressEvent(raw: string): DetectionProgressEvent | null {
  try {
    const data: JsonRecord = record(JSON.parse(raw));
    return {
      jobId: string(data, "jobId"),
      status: status(data),
      progress: number(data, "progress"),
      message: nullableString(data, "message"),
      errorCode: nullableString(data, "errorCode"),
      timestamp: string(data, "timestamp"),
    };
  } catch {
    return null;
  }
}

/** GET /detections: server-side pagination, newest first. */
export function listDetections(
  query: DetectionHistoryQuery = {},
  signal?: AbortSignal,
): Promise<PageResponse<DetectionJobSummary>> {
  return request(async () => {
    const params: Record<string, string | number> = {};
    if (query.page !== undefined) params.page = query.page;
    if (query.size !== undefined) params.size = query.size;
    if (query.status) params.status = query.status;
    if (query.modelKey) params.modelKey = query.modelKey;
    const { data } = await apiClient.get<unknown>("/detections", { params, signal });
    const body = record(data);
    return {
      content: array(body.content).map(toSummary),
      page: number(body, "page"),
      size: number(body, "size"),
      totalElements: number(body, "totalElements"),
      totalPages: number(body, "totalPages"),
    };
  });
}

/** Total number of jobs matching a filter, read from pagination metadata (size=1). */
export async function countDetections(
  query: Omit<DetectionHistoryQuery, "page" | "size"> = {},
  signal?: AbortSignal,
): Promise<number> {
  const page = await listDetections({ ...query, page: 0, size: 1 }, signal);
  return page.totalElements;
}

/** GET /detections/{jobId}. */
export function getDetection(jobId: string, signal?: AbortSignal): Promise<DetectionJob> {
  return request(async () => {
    const { data } = await apiClient.get<unknown>(
      `/detections/${encodeURIComponent(jobId)}`,
      { signal },
    );
    return toDetectionJob(data);
  });
}

/** GET /detections/{jobId}/result: only available for COMPLETED jobs (409 otherwise). */
export function getDetectionResult(
  jobId: string,
  signal?: AbortSignal,
): Promise<DetectionResultMetadata> {
  return request(async () => {
    const { data } = await apiClient.get<unknown>(
      `/detections/${encodeURIComponent(jobId)}/result`,
      { signal },
    );
    return toResult(data);
  });
}

/**
 * POST /detections. Returns the job accepted with HTTP 202. Never retried automatically:
 * a timeout or network error does not prove the job was rejected (see ApiError.kind).
 */
export function createDetection(
  body: CreateDetectionRequest,
  signal?: AbortSignal,
): Promise<DetectionJobAccepted> {
  return request(async () => {
    const { data } = await apiClient.post<unknown>("/detections", body, { signal });
    const accepted = record(data);
    return {
      jobId: string(accepted, "jobId"),
      status: status(accepted),
      progress: number(accepted, "progress"),
      modelKey: string(accepted, "modelKey"),
      message: string(accepted, "message"),
    };
  });
}

/** Relative SSE URL, so EventSource goes through the same proxy as Axios. */
export function detectionEventsUrl(jobId: string): string {
  return `${API_BASE_URL}/detections/${encodeURIComponent(jobId)}/events`;
}
