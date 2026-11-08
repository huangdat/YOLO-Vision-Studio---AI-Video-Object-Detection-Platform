import axios from "axios";
import type { ApiProblem } from "../types/api";

/**
 * Base path of the Spring Boot API. Relative by default so the Vite dev proxy (and any
 * reverse proxy in front of the built app) forwards requests; never a hardcoded host.
 */
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "/api/v1"
).replace(/\/+$/, "");

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10_000,
  headers: { Accept: "application/json" },
});

export type ApiErrorKind =
  | "network"
  | "timeout"
  | "http"
  | "cancelled"
  | "invalid-response";

/** Every API failure is normalised to this type with a user-presentable message. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly code?: string;
  readonly fieldErrors: Record<string, string>;
  readonly problem?: ApiProblem;

  constructor(
    kind: ApiErrorKind,
    message: string,
    options: { status?: number; problem?: ApiProblem } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status;
    this.problem = options.problem;
    this.code = options.problem?.code;
    this.fieldErrors = options.problem?.errors ?? {};
  }

  /** True when the user can usefully retry (connectivity or server-side failures). */
  get retryable(): boolean {
    return (
      this.kind === "network" ||
      this.kind === "timeout" ||
      this.kind === "invalid-response" ||
      (this.status !== undefined && this.status >= 500)
    );
  }
}

export const MESSAGES = {
  network:
    "Unable to connect to the backend. Check that it is running and try again.",
  timeout: "The backend did not respond in time. Please try again.",
  invalid: "The backend returned an unexpected response.",
  cancelled: "The request was cancelled.",
} as const;

function isProblem(value: unknown): value is ApiProblem {
  return (
    typeof value === "object" &&
    value !== null &&
    ("detail" in value || "code" in value || "title" in value)
  );
}

/** Converts Axios, validation, and unknown errors into an ApiError. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (axios.isCancel(error)) {
    return new ApiError("cancelled", MESSAGES.cancelled);
  }
  if (axios.isAxiosError(error)) {
    if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
      return new ApiError("timeout", MESSAGES.timeout);
    }
    const response = error.response;
    if (!response) {
      return new ApiError("network", MESSAGES.network);
    }
    const problem = isProblem(response.data) ? response.data : undefined;
    // A proxy with no backend behind it answers 5xx without a problem body.
    const message =
      problem?.detail ||
      (response.status >= 500
        ? `The backend is unavailable (HTTP ${response.status}). Please try again.`
        : `The request failed (HTTP ${response.status}).`);
    return new ApiError("http", message, { status: response.status, problem });
  }
  if (error instanceof Error) {
    return new ApiError("invalid-response", error.message || MESSAGES.invalid);
  }
  return new ApiError("invalid-response", MESSAGES.invalid);
}

export function isCancelled(error: unknown): boolean {
  return toApiError(error).kind === "cancelled";
}

/** Runs a request and converts any failure into an ApiError. */
export async function request<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error: unknown) {
    throw toApiError(error);
  }
}
