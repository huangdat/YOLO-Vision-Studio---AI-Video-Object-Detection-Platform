import { CanceledError } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import { job, JOB_ID, model, page, result, summary } from "../test/fixtures";
import { apiClient } from "./client";
import {
  countDetections,
  detectionEventsUrl,
  getDetection,
  getDetectionResult,
  isJobId,
  listDetections,
  parseProgressEvent,
} from "./detections";
import { getModel, getModelVersions, listModels } from "./models";

afterEach(() => vi.restoreAllMocks());

describe("model catalog API", () => {
  it("passes server-side filters and parses the catalog", async () => {
    const get = vi
      .spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: { models: [model()], total: 1 } });

    const catalog = await listModels({ version: "YOLO11", size: "n", enabled: false });

    expect(get).toHaveBeenCalledWith("/models", {
      params: { version: "YOLO11", size: "n", enabled: "false" },
      signal: undefined,
    });
    expect(catalog.total).toBe(1);
    expect(catalog.models[0].modelKey).toBe("yolo11n");
  });

  it("omits empty filters", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: { models: [], total: 0 } });
    await listModels({});
    expect(get).toHaveBeenCalledWith("/models", { params: {}, signal: undefined });
  });

  it("reads versions and one model by encoded key", async () => {
    const get = vi
      .spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: { versions: ["YOLOv8", "YOLO11"] } })
      .mockResolvedValueOnce({ data: model({ modelKey: "yolov8n" }) });

    expect((await getModelVersions()).versions).toEqual(["YOLOv8", "YOLO11"]);
    expect((await getModel("yolov8n")).modelKey).toBe("yolov8n");
    expect(get).toHaveBeenLastCalledWith("/models/yolov8n", { signal: undefined });
  });

  it("rejects an HTML fallback page instead of rendering it as data", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: "<!doctype html>" });
    await expect(listModels()).rejects.toMatchObject({ kind: "invalid-response" });
  });
});

describe("detection API", () => {
  it("requests a filtered page and parses it", async () => {
    const get = vi
      .spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: page([summary()], { totalElements: 31, totalPages: 4 }) });

    const history = await listDetections({ page: 2, size: 10, status: "FAILED", modelKey: "yolo11n" });

    expect(get).toHaveBeenCalledWith("/detections", {
      params: { page: 2, size: 10, status: "FAILED", modelKey: "yolo11n" },
      signal: undefined,
    });
    expect(history.totalElements).toBe(31);
    expect(history.content[0].status).toBe("COMPLETED");
  });

  it("counts from pagination metadata with a size of one", async () => {
    const get = vi
      .spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: page([summary()], { totalElements: 125, totalPages: 125, size: 1 }) });

    expect(await countDetections({ status: "COMPLETED" })).toBe(125);
    expect(get).toHaveBeenCalledWith("/detections", {
      params: { page: 0, size: 1, status: "COMPLETED" },
      signal: undefined,
    });
  });

  it("rejects unknown statuses from an incompatible backend", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: page([{ ...summary(), status: "RUNNING" }]),
    });
    await expect(listDetections()).rejects.toMatchObject({ kind: "invalid-response" });
  });

  it("reads job details and results", async () => {
    vi.spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: job() })
      .mockResolvedValueOnce({ data: result() });

    expect((await getDetection(JOB_ID)).progress).toBe(40);
    const metadata = await getDetectionResult(JOB_ID);
    expect(metadata.detectionSummary).toEqual({ bus: 60, car: 12 });
    expect(metadata.countSemantics).toBe("BOUNDING_BOX_DETECTIONS_ACROSS_FRAMES");
  });

  it("propagates request cancellation as a cancelled ApiError", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValueOnce(new CanceledError());
    await expect(getDetection(JOB_ID, new AbortController().signal)).rejects.toMatchObject({
      kind: "cancelled",
    });
  });

  it("validates job ids and builds a relative SSE URL", () => {
    expect(isJobId(JOB_ID)).toBe(true);
    expect(isJobId("not-a-uuid")).toBe(false);
    expect(isJobId(undefined)).toBe(false);
    expect(detectionEventsUrl(JOB_ID)).toBe(`/api/v1/detections/${JOB_ID}/events`);
  });

  it("parses SSE payloads and ignores malformed ones", () => {
    const raw = JSON.stringify({
      jobId: JOB_ID,
      status: "DETECTING",
      progress: 65,
      message: "Detecting objects in video frames",
      errorCode: null,
      timestamp: "2026-11-08T11:13:35Z",
    });
    expect(parseProgressEvent(raw)).toMatchObject({ status: "DETECTING", progress: 65 });
    expect(parseProgressEvent("{not json")).toBeNull();
    expect(parseProgressEvent(JSON.stringify({ jobId: JOB_ID, status: "RUNNING" }))).toBeNull();
  });
});
