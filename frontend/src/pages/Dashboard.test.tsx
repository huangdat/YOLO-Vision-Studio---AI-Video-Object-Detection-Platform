import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, MESSAGES } from "../api/client";
import { countDetections, listDetections } from "../api/detections";
import { getModelVersions, listModels } from "../api/models";
import type { BackendStatus } from "../hooks/useBackendStatus";
import { model, page, summary } from "../test/fixtures";
import { renderAt } from "../test/render";
import { Dashboard } from "./Dashboard";

vi.mock("../api/detections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/detections")>()),
  countDetections: vi.fn(),
  listDetections: vi.fn(),
}));
vi.mock("../api/models", () => ({ listModels: vi.fn(), getModelVersions: vi.fn() }));

const connected: BackendStatus = {
  state: "connected",
  info: { application: "YOLO Vision Studio", service: "backend", version: "1.0.0", status: "UP" },
  checkedAt: new Date("2026-11-08T11:00:00Z"),
};

function counts(values: Record<string, number>) {
  vi.mocked(countDetections).mockImplementation(async (query = {}) => values[query.status ?? "ALL"]);
}

function catalog() {
  vi.mocked(listModels).mockResolvedValue({
    total: 3,
    models: [
      model({ modelKey: "yolov8n", version: "YOLOv8", enabled: true }),
      model({ modelKey: "yolo11n", version: "YOLO11", enabled: true }),
      model({ modelKey: "yolo11s", version: "YOLO11", modelSize: "s" }),
    ],
  });
  vi.mocked(getModelVersions).mockResolvedValue({ versions: ["YOLOv8", "YOLO11"] });
}

function renderDashboard() {
  return renderAt("/", "/", <Dashboard status={connected} refresh={vi.fn(async () => {})} />);
}

function stat(label: string) {
  const heading = screen.getByRole("heading", { name: label });
  return heading.closest("article")!.querySelector(".stat-value")!.textContent;
}

beforeEach(() => {
  counts({ ALL: 125, COMPLETED: 98, FAILED: 7, CANCELLED: 0 });
  catalog();
  vi.mocked(listDetections).mockResolvedValue(
    page([summary(), summary({ jobId: "11111111-1111-1111-1111-111111111111", status: "DETECTING", progress: 40, completedAt: null })], {
      totalElements: 125,
      totalPages: 25,
      size: 5,
    }),
  );
});
afterEach(cleanup);

describe("Dashboard", () => {
  it("shows totals from pagination metadata, not from the rows of one page", async () => {
    renderDashboard();

    await waitFor(() => expect(stat("Total jobs")).toBe("125"));
    expect(stat("Completed")).toBe("98");
    expect(stat("Failed")).toBe("7");
    expect(stat("In progress")).toBe("20");
    expect(stat("YOLO models")).toBe("3");
    expect(screen.getByText("2 enabled for detection")).toBeTruthy();
    // Status counts use filtered count queries; the recent list is a bounded page of 5.
    expect(countDetections).toHaveBeenCalledWith({ status: "COMPLETED" }, expect.any(AbortSignal));
    expect(listDetections).toHaveBeenCalledWith({ page: 0, size: 5 }, expect.any(AbortSignal));
  });

  it("lists recent activity with links to job details and to the history", async () => {
    renderDashboard();

    const table = await screen.findByRole("table", { name: "Recent detection jobs" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("Detecting")).toBeTruthy();
    expect(
      within(table).getAllByRole("link", { name: /View details/ })[0].getAttribute("href"),
    ).toBe("/detections/596b71b1-ea62-4d75-8f34-679e3bd0b5c9");
    expect(screen.getByRole("link", { name: /View all history/ }).getAttribute("href")).toBe("/history");
  });

  it("welcomes the user with a primary Start new detection action", async () => {
    renderDashboard();
    expect(screen.getByRole("heading", { level: 1, name: "Welcome to YOLO Vision Studio" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Start new detection/ }).getAttribute("href")).toBe("/detection");
    expect(screen.getByRole("link", { name: "View history" }).getAttribute("href")).toBe("/history");
    // The decorative model-family list was removed; the catalog is summarised by one KPI.
    await screen.findByRole("table", { name: "Recent detection jobs" });
    expect(screen.queryByRole("heading", { name: "Available YOLO families" })).toBeNull();
    expect(screen.queryByText("1 models")).toBeNull();
  });

  it("shows loading placeholders before data arrives", () => {
    vi.mocked(listDetections).mockReturnValue(new Promise(() => {}));
    renderDashboard();
    expect(screen.getByText("Loading recent jobs")).toBeTruthy();
  });

  it("shows an empty state when there are no jobs", async () => {
    counts({ ALL: 0, COMPLETED: 0, FAILED: 0, CANCELLED: 0 });
    vi.mocked(listDetections).mockResolvedValue(page([]));
    renderDashboard();
    expect(await screen.findByText("No detection jobs yet")).toBeTruthy();
    await waitFor(() => expect(stat("Total jobs")).toBe("0"));
  });

  it("shows a backend failure without fake numbers and retries", async () => {
    vi.mocked(countDetections).mockRejectedValue(new ApiError("network", MESSAGES.network));
    renderDashboard();

    const alert = await screen.findByText("Job statistics are unavailable");
    expect(alert.closest("[role=alert]")?.textContent).toContain(MESSAGES.network);
    expect(screen.queryByRole("heading", { name: "Total jobs" })).toBeNull();

    counts({ ALL: 3, COMPLETED: 1, FAILED: 1, CANCELLED: 0 });
    fireEvent.click(within(alert.closest("[role=alert]") as HTMLElement).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(stat("Total jobs")).toBe("3"));
    expect(stat("In progress")).toBe("1");
  });

  it("never shows a negative in-progress count when counts change between queries", async () => {
    counts({ ALL: 5, COMPLETED: 5, FAILED: 1, CANCELLED: 0 });
    renderDashboard();
    await waitFor(() => expect(stat("In progress")).toBe("0"));
  });
});
