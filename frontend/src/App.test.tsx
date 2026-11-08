import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { getSystemInfo } from "./api/system";

vi.mock("./api/system", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api/system")>()),
  getSystemInfo: vi.fn(),
}));

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

  it("routes to the detection placeholder without exposing a detection form", async () => {
    vi.mocked(getSystemInfo).mockResolvedValueOnce(info);
    render(
      <MemoryRouter initialEntries={["/detection"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Detection" })).toBeTruthy();
    expect(screen.getByText(/this feature is not available yet/)).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    await screen.findByText("Backend connected");
  });
});
