import { ApiError, MESSAGES } from "./client";
import { DETECTION_JOB_STATUSES, type DetectionJobStatus } from "../types/detections";

/**
 * Minimal runtime checks of response shapes. They catch a proxy serving HTML or an
 * incompatible backend instead of rendering undefined values as if they were data.
 */
export type JsonRecord = Record<string, unknown>;

export function invalid(): never {
  throw new ApiError("invalid-response", MESSAGES.invalid);
}

export function record(value: unknown): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    invalid();
  }
  return value as JsonRecord;
}

export function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) {
    invalid();
  }
  return value;
}

export function string(data: JsonRecord, key: string): string {
  const value = data[key];
  if (typeof value !== "string") {
    invalid();
  }
  return value;
}

export function nullableString(data: JsonRecord, key: string): string | null {
  const value = data[key];
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value !== "string") {
    invalid();
  }
  return value;
}

export function number(data: JsonRecord, key: string): number {
  const value = data[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    invalid();
  }
  return value;
}

export function nullableNumber(data: JsonRecord, key: string): number | null {
  const value = data[key];
  if (value === null || value === undefined) {
    return null;
  }
  return number(data, key);
}

export function boolean(data: JsonRecord, key: string): boolean {
  const value = data[key];
  if (typeof value !== "boolean") {
    invalid();
  }
  return value;
}

export function status(data: JsonRecord, key = "status"): DetectionJobStatus {
  const value = data[key];
  if (!DETECTION_JOB_STATUSES.includes(value as DetectionJobStatus)) {
    invalid();
  }
  return value as DetectionJobStatus;
}
