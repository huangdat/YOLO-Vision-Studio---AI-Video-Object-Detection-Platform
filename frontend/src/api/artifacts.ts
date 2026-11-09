import type { AxiosResponseHeaders, RawAxiosResponseHeaders } from "axios";
import { API_BASE_URL, ApiError, apiClient, MESSAGES, request } from "./client";

/**
 * Artifacts of completed jobs, always through Spring Boot on relative same-origin URLs:
 * the browser never receives storage URLs, buckets, object keys, or credentials.
 * Videos are loaded by the <video> element and downloads by ordinary navigation, so MP4
 * bytes never pass through JavaScript.
 */
const base = (jobId: string) => `${API_BASE_URL}/detections/${encodeURIComponent(jobId)}`;

/** Inline MP4 for <video>; supports HTTP Range requests for seeking. */
export function detectionVideoUrl(jobId: string): string {
  return `${base(jobId)}/video`;
}

/** The same MP4 as an attachment (detection-<jobId>.mp4, named by the server). */
export function detectionVideoDownloadUrl(jobId: string): string {
  return `${base(jobId)}/video/download`;
}

/** The worker's original result.json as an attachment (detection-<jobId>-result.json). */
export function resultJsonDownloadUrl(jobId: string): string {
  return `${base(jobId)}/result.json/download`;
}

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface ResultJsonArtifact {
  /** The stored JSON re-indented for reading; the download keeps the original bytes. */
  formatted: string;
  value: { [key: string]: JsonValue };
}

/**
 * Bodies are kept as text: a successful artifact is parsed explicitly below, and only error
 * bodies (problem details) are parsed so ApiError keeps its code.
 */
export function textResponse(
  data: unknown,
  _headers?: AxiosResponseHeaders | RawAxiosResponseHeaders,
  statusCode?: number,
): unknown {
  if (typeof data === "string" && statusCode !== undefined && statusCode >= 400) {
    try {
      return JSON.parse(data) as unknown;
    } catch {
      return data;
    }
  }
  return data;
}

/** GET /detections/{jobId}/result.json: the stored artifact, not the /result metadata DTO. */
export function getResultJson(jobId: string, signal?: AbortSignal): Promise<ResultJsonArtifact> {
  return request(async () => {
    const { data } = await apiClient.get<unknown>(`${relative(jobId)}/result.json`, {
      signal,
      responseType: "text",
      transformResponse: [textResponse],
    });
    if (typeof data !== "string") throw new ApiError("invalid-response", MESSAGES.invalid);
    let value: unknown;
    try {
      value = JSON.parse(data);
    } catch {
      throw new ApiError("invalid-response", "The stored result JSON could not be parsed.");
    }
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new ApiError("invalid-response", "The stored result JSON is not a JSON object.");
    }
    const object = value as { [key: string]: JsonValue };
    return { value: object, formatted: JSON.stringify(object, null, 2) };
  });
}

/**
 * Lightweight availability probe used after a playback error: requests a single byte so the
 * backend's problem code (ARTIFACT_NOT_FOUND, STORAGE_UNAVAILABLE, …) can be shown without
 * downloading the video again. Resolves when the video is available.
 */
export function probeDetectionVideo(jobId: string, signal?: AbortSignal): Promise<void> {
  return request(async () => {
    await apiClient.get<unknown>(`${relative(jobId)}/video`, {
      signal,
      headers: { Range: "bytes=0-0" },
      responseType: "text",
      transformResponse: [textResponse],
    });
  });
}

function relative(jobId: string): string {
  return `/detections/${encodeURIComponent(jobId)}`;
}
