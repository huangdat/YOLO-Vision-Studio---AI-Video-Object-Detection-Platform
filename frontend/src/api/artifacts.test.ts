import { afterEach, describe, expect, it, vi } from "vitest";
import { JOB_ID } from "../test/fixtures";
import {
  detectionVideoDownloadUrl,
  detectionVideoUrl,
  getResultJson,
  probeDetectionVideo,
  resultJsonDownloadUrl,
  textResponse,
} from "./artifacts";
import { apiClient } from "./client";

afterEach(() => vi.restoreAllMocks());

describe("artifact API", () => {
  it("builds relative same-origin URLs without hosts, keys, or credentials", () => {
    expect(detectionVideoUrl(JOB_ID)).toBe(`/api/v1/detections/${JOB_ID}/video`);
    expect(detectionVideoDownloadUrl(JOB_ID)).toBe(`/api/v1/detections/${JOB_ID}/video/download`);
    expect(resultJsonDownloadUrl(JOB_ID)).toBe(`/api/v1/detections/${JOB_ID}/result.json/download`);
    expect(detectionVideoUrl("a/b?c")).toBe("/api/v1/detections/a%2Fb%3Fc/video");
  });

  it("reads result.json as text through the shared client and formats it", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: '{"jobId":"x","statistics":{"bus":60}}' });

    const artifact = await getResultJson(JOB_ID);

    expect(get).toHaveBeenCalledWith(
      `/detections/${JOB_ID}/result.json`,
      expect.objectContaining({ responseType: "text" }),
    );
    expect(artifact.value).toEqual({ jobId: "x", statistics: { bus: 60 } });
    expect(artifact.formatted).toBe('{\n  "jobId": "x",\n  "statistics": {\n    "bus": 60\n  }\n}');
  });

  it.each([
    ["{not json", "The stored result JSON could not be parsed."],
    ["[1,2]", "The stored result JSON is not a JSON object."],
    ["null", "The stored result JSON is not a JSON object."],
  ])("rejects the malformed result.json %s", async (body, message) => {
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: body });
    await expect(getResultJson(JOB_ID)).rejects.toMatchObject({ kind: "invalid-response", message });
  });

  it("probes the video with a single-byte range instead of downloading it", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: "x" });

    await probeDetectionVideo(JOB_ID);

    expect(get).toHaveBeenCalledWith(
      `/detections/${JOB_ID}/video`,
      expect.objectContaining({ headers: { Range: "bytes=0-0" }, responseType: "text" }),
    );
  });

  it("parses problem bodies of failed text responses so error codes survive", () => {
    const problem = '{"code":"ARTIFACT_NOT_FOUND","detail":"Not available."}';
    expect(textResponse(problem, undefined, 404)).toEqual({ code: "ARTIFACT_NOT_FOUND", detail: "Not available." });
    expect(textResponse("<html>bad gateway</html>", undefined, 502)).toBe("<html>bad gateway</html>");
    // Successful bodies stay untouched text; MP4 or JSON bytes are never auto-parsed.
    expect(textResponse('{"a":1}', undefined, 200)).toBe('{"a":1}');
  });
});
