import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { countDetections, getDetection, listDetections } from "./api/detections";
import { getModelVersions, listModels } from "./api/models";
import { getSystemInfo } from "./api/system";
import { job, JOB_ID, page } from "./test/fixtures";

vi.mock("./api/system", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api/system")>()),
  getSystemInfo: vi.fn(),
}));
vi.mock("./api/detections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api/detections")>()),
  countDetections: vi.fn(),
  listDetections: vi.fn(),
  getDetection: vi.fn(),
}));
vi.mock("./api/models", () => ({ listModels: vi.fn(), getModelVersions: vi.fn() }));

beforeEach(() => {
  vi.mocked(countDetections).mockResolvedValue(0);
  vi.mocked(listDetections).mockResolvedValue(page([]));
  vi.mocked(listModels).mockResolvedValue({ models: [], total: 0 });
  vi.mocked(getModelVersions).mockResolvedValue({ versions: [] });
  vi.mocked(getDetection).mockResolvedValue(job({ status: "COMPLETED", progress: 100 }));
});

const info = {
  application: "YOLO Vision Studio",
  service: "backend" as const,
  version: "1.0.0",
  status: "UP" as const,
};
afterEach(cleanup);

describe("workspace", () => {
  it("shows the real backend version after a successful connection", async () => {
    vi.mocked(getSystemInfo).mockResolvedValueOnce(info);
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getAllByText("Checking backend").length).toBeGreaterThan(0);
    expect(await screen.findByText("Spring Boot · v1.0.0")).toBeTruthy();
    expect(screen.getAllByText("Backend connected").length).toBe(2);
  });

  it("shows a backend failure and lets the user retry successfully", async () => {
    vi.mocked(getSystemInfo)
      .mockRejectedValueOnce(new Error("Backend unavailable"))
      .mockResolvedValueOnce(info);
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Backend unavailable",
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(await screen.findByText("Spring Boot · v1.0.0")).toBeTruthy();
  });

  it("routes /detection to the detection workspace without a 'Soon' marker", async () => {
    vi.mocked(getSystemInfo).mockResolvedValueOnce(info);
    render(
      <MemoryRouter initialEntries={["/detection"]}>
        <App />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Video Detection Workspace" }),
    ).toBeTruthy();
    expect(screen.getByRole("textbox", { name: /YouTube video URL/ })).toBeTruthy();
    const navLink = screen.getByRole("link", { name: "Detection" });
    expect(navLink.className).toContain("active");
    expect(navLink.textContent).not.toContain("Soon");
    expect(await screen.findByText("No models are registered.")).toBeTruthy();
    await screen.findByText("Backend connected");
  });

  it.each([
    ["/history", "History"],
    ["/models", "Models"],
  ])("routes %s to its implemented page without a 'Soon' marker", async (path, title) => {
    vi.mocked(getSystemInfo).mockResolvedValueOnce(info);
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 1, name: title })).toBeTruthy();
    const navLink = screen.getByRole("link", { name: title });
    expect(navLink.className).toContain("active");
    expect(navLink.textContent).not.toContain("Soon");
    await screen.findByText("Backend connected");
  });

  it("routes job details and keeps History highlighted", async () => {
    vi.mocked(getSystemInfo).mockResolvedValueOnce(info);
    render(
      <MemoryRouter initialEntries={[`/detections/${JOB_ID}`]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { level: 1, name: "Job 596b71b1" })).toBeTruthy();
    expect(screen.getByText("Detection job")).toBeTruthy();
    expect(screen.getByRole("link", { name: "History" }).className).toContain("active");
    await screen.findByText("Backend connected");
  });
});
