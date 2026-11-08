import { act, cleanup, renderHook } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { getDetection } from "../api/detections";
import { FakeEventSource, job, JOB_ID, progressEvent } from "../test/fixtures";
import { isNewerSnapshot, useDetectionProgress } from "./useDetectionProgress";

vi.mock("../api/detections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/detections")>()),
  getDetection: vi.fn(),
}));

beforeEach(() => {
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function stream() {
  const [source] = FakeEventSource.open();
  expect(source).toBeDefined();
  return source;
}

describe("useDetectionProgress", () => {
  it("connects through the relative proxy path and applies the initial snapshot", () => {
    const { result } = renderHook(() => useDetectionProgress(JOB_ID, { enabled: true }));
    expect(result.current.connection).toBe("connecting");
    expect(stream().url).toBe(`/api/v1/detections/${JOB_ID}/events`);

    act(() => {
      stream().open();
      stream().emit("detection.progress", progressEvent("QUEUED", 0, "2026-11-08T11:13:21Z"));
    });

    expect(result.current.connection).toBe("live");
    expect(result.current.event).toMatchObject({ status: "QUEUED", progress: 0 });
  });

  it("updates on progress events and ignores stale or backward ones", () => {
    const { result } = renderHook(() => useDetectionProgress(JOB_ID, { enabled: true }));
    act(() => {
      stream().emit("detection.progress", progressEvent("DETECTING", 51, "2026-11-08T11:13:35Z"));
      stream().emit("detection.progress", progressEvent("DETECTING", 36, "2026-11-08T11:13:34Z"));
      stream().emit("detection.progress", progressEvent("QUEUED", 0, "2026-11-08T11:13:36Z"));
      stream().emit("detection.progress", "{malformed");
    });
    expect(result.current.event).toMatchObject({ status: "DETECTING", progress: 51 });

    act(() => stream().emit("detection.progress", progressEvent("ENCODING", 85, "2026-11-08T11:13:37Z")));
    expect(result.current.event).toMatchObject({ status: "ENCODING", progress: 85 });
  });

  it.each([
    ["detection.completed", "COMPLETED", 100],
    ["detection.failed", "FAILED", 12],
    ["detection.cancelled", "CANCELLED", 20],
  ] as const)("closes the stream on %s", (name, status, progress) => {
    const { result } = renderHook(() => useDetectionProgress(JOB_ID, { enabled: true }));
    const source = stream();

    act(() =>
      source.emit(name, progressEvent(status, progress, "2026-11-08T11:13:38Z", {
        errorCode: status === "FAILED" ? "VIDEO_DOWNLOAD_FAILED" : null,
      })),
    );

    expect(result.current.event?.status).toBe(status);
    expect(result.current.connection).toBe("closed");
    expect(source.closed).toBe(true);
    // A terminal snapshot is final: later events cannot overwrite it.
    act(() => source.emit("detection.progress", progressEvent("DETECTING", 50, "2026-11-08T12:00:00Z")));
    expect(result.current.event?.status).toBe(status);
  });

  it("reports transient disconnects and recovers with the next snapshot", () => {
    const { result } = renderHook(() => useDetectionProgress(JOB_ID, { enabled: true }));
    act(() => stream().fail());
    expect(result.current.connection).toBe("reconnecting");

    act(() => {
      stream().open();
      stream().emit("detection.progress", progressEvent("DETECTING", 70, "2026-11-08T11:13:36Z"));
    });
    expect(result.current.connection).toBe("live");
    expect(result.current.event?.progress).toBe(70);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("falls back to conservative polling when the stream is rejected, and stops at a terminal state", async () => {
    vi.useFakeTimers();
    vi.mocked(getDetection)
      .mockResolvedValueOnce(job({ status: "DETECTING", progress: 60, updatedAt: "2026-11-08T11:13:36Z" }))
      .mockResolvedValueOnce(job({ status: "COMPLETED", progress: 100, updatedAt: "2026-11-08T11:13:38Z" }));
    const { result } = renderHook(() =>
      useDetectionProgress(JOB_ID, { enabled: true, pollIntervalMs: 5_000 }),
    );

    act(() => stream().fail(true));
    expect(result.current.connection).toBe("polling");
    expect(FakeEventSource.open()).toHaveLength(0);
    expect(getDetection).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(result.current.event).toMatchObject({ status: "DETECTING", progress: 60 });

    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(result.current.event).toMatchObject({ status: "COMPLETED", progress: 100 });
    expect(result.current.connection).toBe("closed");

    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(getDetection).toHaveBeenCalledTimes(2);
  });

  it("switches to polling after repeated stream errors", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useDetectionProgress(JOB_ID, { enabled: true, maxStreamErrors: 3 }),
    );
    act(() => {
      stream().fail();
      stream().fail();
    });
    expect(result.current.connection).toBe("reconnecting");
    act(() => stream().fail());
    expect(result.current.connection).toBe("polling");
  });

  it("stops polling when the job no longer exists", async () => {
    vi.useFakeTimers();
    vi.mocked(getDetection).mockRejectedValue(new ApiError("http", "Not found", { status: 404 }));
    vi.stubGlobal("EventSource", undefined);
    const { result } = renderHook(() => useDetectionProgress(JOB_ID, { enabled: true }));
    expect(result.current.connection).toBe("polling");

    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(result.current.connection).toBe("closed");
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(getDetection).toHaveBeenCalledTimes(1);
  });

  it("closes the stream on unmount", () => {
    const { unmount } = renderHook(() => useDetectionProgress(JOB_ID, { enabled: true }));
    const source = stream();
    unmount();
    expect(source.closed).toBe(true);
  });

  it("keeps a single open connection under StrictMode double effects", () => {
    const wrapper = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>;
    renderHook(() => useDetectionProgress(JOB_ID, { enabled: true }), { wrapper });
    expect(FakeEventSource.open()).toHaveLength(1);
  });

  it("does not connect when disabled or for an invalid id", () => {
    renderHook(() => useDetectionProgress(JOB_ID, { enabled: false }));
    renderHook(() => useDetectionProgress("not-a-uuid", { enabled: true }));
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("ignores events for a different job", () => {
    const { result } = renderHook(() => useDetectionProgress(JOB_ID, { enabled: true }));
    act(() =>
      stream().emit("detection.progress", {
        ...progressEvent("DETECTING", 30, "2026-11-08T11:13:30Z"),
        jobId: "11111111-1111-1111-1111-111111111111",
      }),
    );
    expect(result.current.event).toBeNull();
  });
});

describe("isNewerSnapshot", () => {
  it("never replaces a terminal snapshot", () => {
    expect(
      isNewerSnapshot(
        progressEvent("DETECTING", 10, "2026-11-08T12:00:00Z"),
        progressEvent("FAILED", 10, "2026-11-08T11:00:00Z"),
      ),
    ).toBe(false);
  });
});
