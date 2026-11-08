import { AxiosError, AxiosHeaders, CanceledError } from "axios";
import { describe, expect, it } from "vitest";
import { API_BASE_URL, ApiError, MESSAGES, request, toApiError } from "./client";

function httpError(status: number, data: unknown): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError("Request failed", "ERR_BAD_RESPONSE", { headers }, null, {
    status,
    statusText: "",
    headers: {},
    config: { headers },
    data,
  });
}

describe("API client", () => {
  it("uses a relative base path so the Vite proxy is used", () => {
    expect(API_BASE_URL).toBe("/api/v1");
  });

  it("returns successful results unchanged", async () => {
    await expect(request(async () => ({ ok: true }))).resolves.toEqual({ ok: true });
  });

  it("maps backend problem details to a typed error with code and field errors", () => {
    const error = toApiError(
      httpError(400, {
        title: "Bad Request",
        status: 400,
        detail: "Detection request validation failed.",
        code: "INVALID_DETECTION_REQUEST",
        errors: { videoUrl: "must be a supported YouTube video URL" },
      }),
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe("http");
    expect(error.status).toBe(400);
    expect(error.code).toBe("INVALID_DETECTION_REQUEST");
    expect(error.message).toBe("Detection request validation failed.");
    expect(error.fieldErrors).toEqual({ videoUrl: "must be a supported YouTube video URL" });
    expect(error.retryable).toBe(false);
  });

  it("maps not-found problems without making them retryable", () => {
    const error = toApiError(
      httpError(404, { detail: "The requested detection job does not exist.", code: "JOB_NOT_FOUND" }),
    );
    expect(error.status).toBe(404);
    expect(error.code).toBe("JOB_NOT_FOUND");
    expect(error.retryable).toBe(false);
  });

  it("describes a proxy 5xx without a problem body and allows retry", () => {
    const error = toApiError(httpError(502, "<html>Bad gateway</html>"));
    expect(error.message).toBe("The backend is unavailable (HTTP 502). Please try again.");
    expect(error.retryable).toBe(true);
  });

  it("reports network failures with a user-friendly message", () => {
    const error = toApiError(new AxiosError("Network Error", "ERR_NETWORK"));
    expect(error.kind).toBe("network");
    expect(error.message).toBe(MESSAGES.network);
    expect(error.retryable).toBe(true);
  });

  it("reports timeouts separately", () => {
    expect(toApiError(new AxiosError("timeout", "ECONNABORTED")).kind).toBe("timeout");
  });

  it("recognises cancelled requests", () => {
    expect(toApiError(new CanceledError()).kind).toBe("cancelled");
  });

  it("treats unexpected errors as invalid responses and wraps them via request()", async () => {
    await expect(
      request(async () => {
        throw new TypeError("bad shape");
      }),
    ).rejects.toMatchObject({ kind: "invalid-response", message: "bad shape" });
  });
});
