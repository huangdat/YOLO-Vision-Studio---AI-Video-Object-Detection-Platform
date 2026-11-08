import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, MESSAGES } from "../api/client";
import { listDetections } from "../api/detections";
import { listModels } from "../api/models";
import { model, page, summary } from "../test/fixtures";
import { currentLocation, renderAt } from "../test/render";
import type { DetectionJobSummary } from "../types/detections";
import { History } from "./History";

vi.mock("../api/detections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/detections")>()),
  listDetections: vi.fn(),
}));
vi.mock("../api/models", () => ({ listModels: vi.fn() }));

function jobs(count: number, start = 0): DetectionJobSummary[] {
  return Array.from({ length: count }, (_, index) => {
    const n = String(start + index).padStart(12, "0");
    return summary({ jobId: `00000000-0000-4000-8000-${n}`, createdAt: `2026-11-08T10:${String(59 - start - index).padStart(2, "0")}:00Z` });
  });
}

beforeEach(() => {
  vi.mocked(listModels).mockResolvedValue({
    models: [model({ modelKey: "yolo11n" }), model({ modelKey: "yolov8n", version: "YOLOv8" })],
    total: 2,
  });
  vi.mocked(listDetections).mockImplementation(async (query = {}) => {
    const p = query.page ?? 0;
    return page(jobs(p < 2 ? 10 : 3, p * 10), { page: p, size: 10, totalElements: 23, totalPages: 3 });
  });
});
afterEach(cleanup);

const renderHistory = (path = "/history") => renderAt(path, "/history", <History />);

function rows() {
  const table = screen.getByRole("table", { name: "Detection job history" });
  return within(table).getAllByRole("row").slice(1);
}

describe("History page", () => {
  it("renders a server-side page in the order returned (newest first)", async () => {
    renderHistory();
    await waitFor(() => expect(rows()).toHaveLength(10));
    expect(listDetections).toHaveBeenCalledWith(
      { page: 0, size: 10, status: undefined, modelKey: undefined },
      expect.any(AbortSignal),
    );
    expect(screen.getByText("Showing 1–10 of 23")).toBeTruthy();
    expect(screen.getByText("Page 1 of 3")).toBeTruthy();
    expect(within(rows()[0]).getByText("00000000")).toBeTruthy();
    // Exact accessible name: words must not run together for screen readers.
    expect(within(rows()[0]).getByRole("link", { name: "View details for job 00000000" }).getAttribute("href")).toBe(
      "/detections/00000000-0000-4000-8000-000000000000",
    );
  });

  it("navigates between pages", async () => {
    const view = renderHistory();
    await waitFor(() => expect(rows()).toHaveLength(10));

    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(screen.getByText("Page 2 of 3")).toBeTruthy());
    expect(currentLocation(view.container)).toBe("/history?page=1");

    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(screen.getByText("Showing 21–23 of 23")).toBeTruthy();
    expect((screen.getByRole("button", { name: /Next/ }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Previous/ }));
    await waitFor(() => expect(screen.getByText("Page 2 of 3")).toBeTruthy());
  });

  it("filters by status and model, resetting to the first page", async () => {
    const view = renderHistory("/history?page=2");
    await waitFor(() => expect(rows()).toHaveLength(3));

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "FAILED" } });
    await waitFor(() =>
      expect(listDetections).toHaveBeenLastCalledWith(
        { page: 0, size: 10, status: "FAILED", modelKey: undefined },
        expect.any(AbortSignal),
      ),
    );
    expect(currentLocation(view.container)).toBe("/history?status=FAILED");

    await waitFor(() => expect(screen.getAllByRole("option", { name: "yolov8n" })).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "yolov8n" } });
    await waitFor(() =>
      expect(listDetections).toHaveBeenLastCalledWith(
        { page: 0, size: 10, status: "FAILED", modelKey: "yolov8n" },
        expect.any(AbortSignal),
      ),
    );
  });

  it("ignores a slow response for outdated filters", async () => {
    let resolveSlow: (value: ReturnType<typeof page<DetectionJobSummary>>) => void = () => {};
    vi.mocked(listDetections)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSlow = resolve; }))
      .mockImplementation(async () => page([summary({ status: "FAILED", errorCode: "INVALID_SOURCE" })]));
    renderHistory();

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "FAILED" } });
    await waitFor(() => expect(rows()).toHaveLength(1));
    resolveSlow(page(jobs(10)));
    await Promise.resolve();
    expect(rows()).toHaveLength(1);
    expect(screen.getByText("INVALID_SOURCE")).toBeTruthy();
  });

  it("explains an empty history", async () => {
    vi.mocked(listDetections).mockResolvedValue(page([]));
    renderHistory();
    expect(await screen.findByText("No detection jobs yet.")).toBeTruthy();
    expect(screen.getByText("No records")).toBeTruthy();
  });

  it("explains when filters match nothing", async () => {
    vi.mocked(listDetections).mockResolvedValue(page([]));
    renderHistory("/history?status=CANCELLED");
    expect(await screen.findByText("No jobs match these filters.")).toBeTruthy();
  });

  it("ignores invalid URL parameters instead of sending them", async () => {
    renderHistory("/history?page=-4&size=1000&status=RUNNING&model=../x");
    await waitFor(() =>
      expect(listDetections).toHaveBeenCalledWith(
        { page: 0, size: 10, status: undefined, modelKey: undefined },
        expect.any(AbortSignal),
      ),
    );
  });

  it("shows errors with a retry", async () => {
    vi.mocked(listDetections).mockRejectedValueOnce(new ApiError("network", MESSAGES.network));
    renderHistory();
    expect(await screen.findByText(MESSAGES.network)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(rows()).toHaveLength(10));
  });
});
