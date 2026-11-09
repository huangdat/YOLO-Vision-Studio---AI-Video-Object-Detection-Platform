import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getResultJson, probeDetectionVideo } from "../api/artifacts";
import { ApiError } from "../api/client";
import { getDetection, getDetectionResult } from "../api/detections";
import { FakeEventSource, job, JOB_ID, progressEvent, result } from "../test/fixtures";
import { renderAt } from "../test/render";
import { DetectionDetails } from "./DetectionDetails";

vi.mock("../api/detections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/detections")>()),
  getDetection: vi.fn(),
  getDetectionResult: vi.fn(),
}));
vi.mock("../api/artifacts", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/artifacts")>()),
  getResultJson: vi.fn(),
  probeDetectionVideo: vi.fn(),
}));

const BASE = `/api/v1/detections/${JOB_ID}`;
const completedJob = () =>
  job({ status: "COMPLETED", progress: 100, completedAt: "2026-11-08T11:13:38Z" });

beforeEach(() => {
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.mocked(getResultJson).mockReset();
  vi.mocked(probeDetectionVideo).mockReset();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const renderJob = () => renderAt(`/detections/${JOB_ID}`, "/detections/:jobId", <DetectionDetails />);
const video = () => screen.getByLabelText("Annotated detection video") as HTMLVideoElement;
const problem = (status: number, code: string, detail: string) =>
  new ApiError("http", detail, { status, problem: { code, detail } });

async function completed(overrides: Parameters<typeof result>[0] = {}) {
  vi.mocked(getDetection).mockResolvedValue(completedJob());
  vi.mocked(getDetectionResult).mockResolvedValue(result(overrides));
  renderJob();
  await screen.findByText("Bus detection events");
}

describe("Detected video", () => {
  it("is not offered while the job is still processing", async () => {
    vi.mocked(getDetection).mockResolvedValue(job({ status: "DETECTING", progress: 40 }));
    renderJob();
    await screen.findByText("Detecting");

    expect(screen.queryByLabelText("Annotated detection video")).toBeNull();
    expect(screen.queryByRole("link", { name: /download/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "View JSON result" })).toBeNull();
    expect(getDetectionResult).not.toHaveBeenCalled();
    await waitFor(() => expect(FakeEventSource.open()).toHaveLength(1));
  });

  it("is not offered for failed jobs, which keep their failure details", async () => {
    vi.mocked(getDetection).mockResolvedValue(
      job({ status: "FAILED", progress: 30, errorCode: "DOWNLOAD_FAILED", errorMessage: "The video is unavailable." }),
    );
    renderJob();
    expect(await screen.findByText("DOWNLOAD_FAILED")).toBeTruthy();

    expect(screen.queryByLabelText("Annotated detection video")).toBeNull();
    expect(screen.queryByRole("link", { name: /download/i })).toBeNull();
    expect(getDetectionResult).not.toHaveBeenCalled();
  });

  it("renders an accessible native player for the backend stream without autoplay", async () => {
    await completed();

    const player = video();
    expect(player.getAttribute("src")).toBe(`${BASE}/video`);
    expect(player.controls).toBe(true);
    expect(player.getAttribute("preload")).toBe("metadata");
    expect(player.autoplay).toBe(false);
    expect(player.hasAttribute("playsinline")).toBe(true);
    expect(screen.getByText("Loading video…").getAttribute("role")).toBe("status");

    fireEvent.loadedMetadata(player);
    expect(screen.queryByText("Loading video…")).toBeNull();
    expect(probeDetectionVideo).not.toHaveBeenCalled();
  });

  it("offers MP4 and JSON downloads as plain same-origin links", async () => {
    await completed();

    const mp4 = screen.getByRole("link", { name: "Download detected video" });
    expect(mp4.getAttribute("href")).toBe(`${BASE}/video/download`);
    expect(mp4.hasAttribute("download")).toBe(true);
    expect(mp4.getAttribute("download")).toBe(""); // the server's Content-Disposition names the file
    const json = screen.getByRole("link", { name: "Download JSON" });
    expect(json.getAttribute("href")).toBe(`${BASE}/result.json/download`);
    expect(screen.getAllByRole("link", { name: /download/i })).toHaveLength(2);
  });

  it("explains a job without a recorded video and offers no MP4 download", async () => {
    await completed({ outputVideoAvailable: false });

    expect(screen.getByText("No annotated video was recorded for this job.")).toBeTruthy();
    expect(screen.queryByLabelText("Annotated detection video")).toBeNull();
    expect(screen.queryByRole("link", { name: "Download detected video" })).toBeNull();
    expect(screen.getByRole("link", { name: "Download JSON" })).toBeTruthy();
  });

  it("explains a missing stored video and removes its download", async () => {
    vi.mocked(probeDetectionVideo).mockRejectedValue(
      problem(404, "ARTIFACT_NOT_FOUND", "The requested artifact is not available for this job."),
    );
    await completed();

    fireEvent.error(video());

    expect(await screen.findByText("The detected video is missing")).toBeTruthy();
    expect(probeDetectionVideo).toHaveBeenCalledWith(JOB_ID, expect.any(AbortSignal));
    expect(screen.queryByRole("button", { name: "Retry playback" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Download detected video" })).toBeNull();
    // Statistics stay visible; nothing is resubmitted.
    expect(screen.getByText("Bus detection events")).toBeTruthy();
  });

  it("explains a storage outage and retries playback without touching the job", async () => {
    vi.mocked(probeDetectionVideo).mockRejectedValue(
      problem(503, "STORAGE_UNAVAILABLE", "Artifact storage is temporarily unavailable."),
    );
    await completed();
    const jobCalls = vi.mocked(getDetection).mock.calls.length;

    fireEvent.error(video());
    expect(await screen.findByText("Video storage is temporarily unavailable")).toBeTruthy();
    expect(screen.getByText("Artifact storage is temporarily unavailable.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Retry playback" }));
    expect(video().getAttribute("src")).toBe(`${BASE}/video`);
    expect(screen.getByText("Loading video…")).toBeTruthy();
    expect(vi.mocked(getDetection).mock.calls.length).toBe(jobCalls);
  });

  it("reports an interrupted playback when the video itself is still available", async () => {
    vi.mocked(probeDetectionVideo).mockResolvedValue(undefined);
    await completed();

    const player = video();
    Object.defineProperty(player, "error", { value: { code: 2 }, configurable: true });
    fireEvent.error(player);

    expect(await screen.findByText("Playback was interrupted")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry playback" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download detected video" })).toBeTruthy();
  });

  it("explains a decode failure but keeps the download", async () => {
    vi.mocked(probeDetectionVideo).mockResolvedValue(undefined);
    await completed();

    const player = video();
    Object.defineProperty(player, "error", { value: { code: 4 }, configurable: true });
    fireEvent.error(player);

    expect(await screen.findByText("This browser could not play the video")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download detected video" })).toBeTruthy();
  });

  it("appears after a live completion without opening another event stream", async () => {
    vi.mocked(getDetection)
      .mockResolvedValueOnce(job())
      .mockResolvedValue(completedJob());
    vi.mocked(getDetectionResult).mockResolvedValue(result());
    renderJob();
    await screen.findByText("Detecting");
    expect(screen.queryByLabelText("Annotated detection video")).toBeNull();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    const [source] = FakeEventSource.open();
    act(() => source.emit("detection.completed", progressEvent("COMPLETED", 100, "2026-11-08T11:13:38Z")));

    expect(await screen.findByLabelText("Annotated detection video")).toBeTruthy();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.open()).toHaveLength(0);
  });
});

describe("Result JSON viewer", () => {
  it("loads the stored artifact only when opened and shows it as escaped text", async () => {
    const value = { jobId: JOB_ID, note: "<img src=x onerror=alert(1)><script>alert(2)</script>" };
    vi.mocked(getResultJson).mockResolvedValue({ value, formatted: JSON.stringify(value, null, 2) });
    await completed();
    expect(getResultJson).not.toHaveBeenCalled();

    const toggle = screen.getByRole("button", { name: "View JSON result" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);

    const viewer = await screen.findByLabelText("Raw result JSON");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(viewer.textContent).toContain('"note": "<img src=x onerror=alert(1)><script>alert(2)</script>"');
    expect(viewer.querySelector("img, script")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText(/separate representation/)).toBeTruthy();
    // The database statistics stay visible alongside the raw artifact.
    expect(screen.getByText("Bus detection events")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Hide JSON result" }));
    expect(screen.queryByLabelText("Raw result JSON")).toBeNull();
  });

  it("shows a loading state, then errors with a retry", async () => {
    let reject: (error: unknown) => void = () => undefined;
    vi.mocked(getResultJson)
      .mockReturnValueOnce(new Promise((_, fail) => (reject = fail)))
      .mockResolvedValueOnce({ value: { a: 1 }, formatted: '{\n  "a": 1\n}' });
    await completed();

    fireEvent.click(screen.getByRole("button", { name: "View JSON result" }));
    expect(screen.getByText("Loading result JSON")).toBeTruthy();
    act(() => reject(problem(503, "STORAGE_UNAVAILABLE", "Artifact storage is temporarily unavailable.")));

    expect(await screen.findByText("The result JSON could not be loaded")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect((await screen.findByLabelText("Raw result JSON")).textContent).toBe('{\n  "a": 1\n}');
  });

  it("reports malformed stored JSON without rendering it", async () => {
    vi.mocked(getResultJson).mockRejectedValue(
      new ApiError("invalid-response", "The stored result JSON could not be parsed."),
    );
    await completed();

    fireEvent.click(screen.getByRole("button", { name: "View JSON result" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("The stored result JSON could not be parsed.")).toBeTruthy();
    expect(screen.queryByLabelText("Raw result JSON")).toBeNull();
  });

  it("copies the formatted JSON and reports when copying is unavailable", async () => {
    vi.mocked(getResultJson).mockResolvedValue({ value: { a: 1 }, formatted: '{\n  "a": 1\n}' });
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    await completed();

    fireEvent.click(screen.getByRole("button", { name: "View JSON result" }));
    fireEvent.click(await screen.findByRole("button", { name: "Copy JSON" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('{\n  "a": 1\n}'));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();

    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    fireEvent.click(screen.getByRole("button", { name: "Hide JSON result" }));
    fireEvent.click(screen.getByRole("button", { name: "View JSON result" }));
    fireEvent.click(await screen.findByRole("button", { name: "Copy JSON" }));
    expect(await screen.findByText("Copying is not available in this browser.")).toBeTruthy();
  });

  it("is not offered when no result.json was recorded", async () => {
    await completed({ resultMetadataAvailable: false });

    expect(screen.queryByRole("button", { name: "View JSON result" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Download JSON" })).toBeNull();
    expect(screen.getByRole("link", { name: "Download detected video" })).toBeTruthy();
  });
});
