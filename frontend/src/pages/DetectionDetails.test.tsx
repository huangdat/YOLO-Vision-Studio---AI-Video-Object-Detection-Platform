import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, MESSAGES } from "../api/client";
import { getDetection, getDetectionResult } from "../api/detections";
import { FakeEventSource, job, JOB_ID, progressEvent, result } from "../test/fixtures";
import { renderAt } from "../test/render";
import { DetectionDetails } from "./DetectionDetails";

vi.mock("../api/detections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/detections")>()),
  getDetection: vi.fn(),
  getDetectionResult: vi.fn(),
}));

beforeEach(() => {
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const renderJob = (id = JOB_ID) =>
  renderAt(`/detections/${id}`, "/detections/:jobId", <DetectionDetails />);

function progressValue() {
  return screen.getByRole("progressbar", { name: "Job progress" }).getAttribute("aria-valuenow");
}

describe("Detection details page", () => {
  it("shows a pending job without claiming success and opens a live stream", async () => {
    vi.mocked(getDetection).mockResolvedValue(job({ status: "PENDING", progress: 0, startedAt: null }));
    renderJob();

    expect(await screen.findByText("Pending")).toBeTruthy();
    expect(progressValue()).toBe("0");
    expect(screen.queryByText(/Detection completed/)).toBeNull();
    expect(FakeEventSource.open()).toHaveLength(1);
    expect(await screen.findByText("Connecting to live updates…")).toBeTruthy();
    expect(getDetectionResult).not.toHaveBeenCalled();
  });

  it("shows configuration and applies live progress events", async () => {
    vi.mocked(getDetection).mockResolvedValue(job());
    renderJob();

    expect(await screen.findByText("Detecting")).toBeTruthy();
    expect(screen.getByText("320 px")).toBeTruthy();
    expect(screen.getByText("0.25")).toBeTruthy();
    expect(screen.getAllByText("yolo11n").length).toBeGreaterThan(0);

    act(() => {
      const [source] = FakeEventSource.open();
      source.open();
      source.emit("detection.progress", progressEvent("ENCODING", 85, "2026-11-08T11:13:37Z"));
    });
    expect(screen.getByText("Encoding")).toBeTruthy();
    expect(progressValue()).toBe("85");
    expect(screen.getByText("Live updates")).toBeTruthy();
  });

  it("reloads the job on completion and shows measured result statistics", async () => {
    vi.mocked(getDetection)
      .mockResolvedValueOnce(job())
      .mockResolvedValue(job({ status: "COMPLETED", progress: 100, completedAt: "2026-11-08T11:13:38Z", updatedAt: "2026-11-08T11:13:38Z" }));
    vi.mocked(getDetectionResult).mockResolvedValue(result());
    renderJob();
    await screen.findByText("Detecting");

    act(() =>
      FakeEventSource.open()[0].emit(
        "detection.completed",
        progressEvent("COMPLETED", 100, "2026-11-08T11:13:38Z"),
      ),
    );

    expect(await screen.findByText("Bus detection events")).toBeTruthy();
    expect(FakeEventSource.open()).toHaveLength(0);
    expect(getDetection).toHaveBeenCalledTimes(2);
    const metric = (label: string) =>
      screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent;
    expect(metric("Frames processed")).toBe("60");
    expect(metric("Detection events")).toBe("72");
    expect(metric("Processing time")).toBe("10.3 s");
    expect(metric("Model used")).toBe("yolo11n");
    expect(screen.getByText("Car detection events")).toBeTruthy();
    expect(screen.getByText(/not unique objects/)).toBeTruthy();
    expect(screen.queryByText(/unique (cars|buses)/i)).toBeNull();
    expect(screen.getByText(/Video preview and download will be available in a future phase/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /download/i })).toBeNull();
  });

  it("supports arbitrary class names and no detections", async () => {
    vi.mocked(getDetection).mockResolvedValue(job({ status: "COMPLETED", progress: 100 }));
    vi.mocked(getDetectionResult).mockResolvedValueOnce(
      result({ detectionSummary: { "traffic light": 4 }, totalDetections: 4 }),
    );
    renderJob();
    expect(await screen.findByText("Traffic light detection events")).toBeTruthy();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("explains a completed job without detections", async () => {
    vi.mocked(getDetection).mockResolvedValue(job({ status: "COMPLETED", progress: 100 }));
    vi.mocked(getDetectionResult).mockResolvedValue(result({ detectionSummary: {}, totalDetections: 0 }));
    renderJob();
    expect(await screen.findByText("No objects of the selected classes were detected.")).toBeTruthy();
  });

  it("shows the sanitized failure and no results for a failed job", async () => {
    vi.mocked(getDetection).mockResolvedValue(
      job({ status: "FAILED", progress: 12, errorCode: "VIDEO_DOWNLOAD_FAILED", errorMessage: "The YouTube video could not be downloaded." }),
    );
    renderJob();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("VIDEO_DOWNLOAD_FAILED");
    expect(alert.textContent).toContain("The YouTube video could not be downloaded.");
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(getDetectionResult).not.toHaveBeenCalled();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("rejects an invalid job id without calling the API", async () => {
    renderJob("not-a-job");
    expect(await screen.findByText("Invalid job ID")).toBeTruthy();
    expect(getDetection).not.toHaveBeenCalled();
  });

  it("reports an unknown job", async () => {
    vi.mocked(getDetection).mockRejectedValue(
      new ApiError("http", "The requested detection job does not exist.", { status: 404 }),
    );
    renderJob();
    expect(await screen.findByText("Detection job not found")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("retries after a connection failure", async () => {
    vi.mocked(getDetection)
      .mockRejectedValueOnce(new ApiError("network", MESSAGES.network))
      .mockResolvedValue(job({ status: "QUEUED", progress: 0 }));
    renderJob();
    expect(await screen.findByText(MESSAGES.network)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("Queued")).toBeTruthy());
  });
});

describe("Detection details after submission", () => {
  const renderSubmitted = (state: unknown) =>
    render(
      <MemoryRouter initialEntries={[{ pathname: `/detections/${JOB_ID}`, state }]}>
        <Routes>
          <Route path="/detections/:jobId" element={<DetectionDetails />} />
        </Routes>
      </MemoryRouter>,
    );

  it("confirms the accepted job and reuses the single progress stream", async () => {
    vi.mocked(getDetection).mockResolvedValue(job({ status: "QUEUED", progress: 0, startedAt: null }));
    renderSubmitted({ submitted: { jobId: JOB_ID, status: "QUEUED" } });

    expect(await screen.findByText(/Job submitted\. The backend accepted it/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Start another detection" }).getAttribute("href")).toBe("/detection");
    expect(FakeEventSource.open()).toHaveLength(1);
  });

  it("shows no notice for ordinary visits or another job's state", async () => {
    vi.mocked(getDetection).mockResolvedValue(job({ status: "QUEUED", progress: 0, startedAt: null }));
    renderSubmitted({ submitted: { jobId: "00000000-0000-4000-8000-000000000000" } });
    expect(await screen.findByText("Queued")).toBeTruthy();
    expect(screen.queryByText(/Job submitted/)).toBeNull();
  });
});
