import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, MESSAGES } from "../api/client";
import { getModel, getModelVersions, listModels } from "../api/models";
import { model } from "../test/fixtures";
import { currentLocation, renderAt } from "../test/render";
import { Models } from "./Models";

vi.mock("../api/models", () => ({ listModels: vi.fn(), getModelVersions: vi.fn(), getModel: vi.fn() }));

const all = [
  model({ modelKey: "yolov8n", version: "YOLOv8", modelSize: "n" }),
  model({ modelKey: "yolo11n", version: "YOLO11", modelSize: "n", enabled: true }),
  model({ modelKey: "yolo26s", version: "YOLO26", modelSize: "s" }),
];

beforeEach(() => {
  vi.mocked(getModelVersions).mockResolvedValue({ versions: ["YOLOv8", "YOLO11", "YOLO26"] });
  vi.mocked(listModels).mockImplementation(async (filter = {}) => {
    const models = all.filter(
      (item) =>
        (!filter.version || item.version === filter.version) &&
        (!filter.size || item.modelSize === filter.size) &&
        (filter.enabled === undefined || item.enabled === filter.enabled),
    );
    return { models, total: models.length };
  });
});
afterEach(cleanup);

const renderModels = (path = "/models") => renderAt(path, "/models", <Models />);

function cards() {
  return screen.getAllByRole("listitem").map((item) => item.querySelector("h3")!.textContent);
}

describe("Models page", () => {
  it("renders the actual catalog with administrative status and no download controls", async () => {
    renderModels();
    await waitFor(() => expect(cards()).toEqual(["yolov8n", "yolo11n", "yolo26s"]));
    expect(screen.getByText("3 models registered")).toBeTruthy();
    const yolo11n = screen.getAllByRole("listitem")[1];
    expect(within(yolo11n).getByText("Enabled")).toBeTruthy();
    expect(within(yolo11n).getByText("yolo11n.pt")).toBeTruthy();
    expect(within(screen.getAllByRole("listitem")[0]).getByText("Disabled")).toBeTruthy();
    expect(screen.getByText(/does not confirm that a worker has prepared its weights/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /download|enable/i })).toBeNull();
  });

  it("filters by version through the API and the URL", async () => {
    const view = renderModels();
    await waitFor(() => expect(cards()).toHaveLength(3));
    await waitFor(() => expect((screen.getByLabelText("Version") as HTMLSelectElement).disabled).toBe(false));

    fireEvent.change(screen.getByLabelText("Version"), { target: { value: "YOLO26" } });

    await waitFor(() => expect(cards()).toEqual(["yolo26s"]));
    expect(listModels).toHaveBeenLastCalledWith({ version: "YOLO26" }, expect.any(AbortSignal));
    expect(currentLocation(view.container)).toBe("/models?version=YOLO26");
  });

  it("filters by size and by enabled status, then clears filters", async () => {
    renderModels();
    await waitFor(() => expect(cards()).toHaveLength(3));

    fireEvent.change(screen.getByLabelText("Size"), { target: { value: "n" } });
    await waitFor(() => expect(cards()).toEqual(["yolov8n", "yolo11n"]));
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "true" } });
    await waitFor(() => expect(cards()).toEqual(["yolo11n"]));
    expect(listModels).toHaveBeenLastCalledWith({ size: "n", enabled: true }, expect.any(AbortSignal));

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(cards()).toHaveLength(3));
  });

  it("explains when no model matches", async () => {
    renderModels("/models?version=YOLO26&enabled=true");
    expect(await screen.findByText("No models match these filters.")).toBeTruthy();
  });

  it("explains an empty catalog", async () => {
    vi.mocked(listModels).mockResolvedValue({ models: [], total: 0 });
    renderModels();
    expect(await screen.findByText("No models are registered.")).toBeTruthy();
  });

  it("shows API errors with a retry", async () => {
    vi.mocked(listModels).mockRejectedValueOnce(new ApiError("network", MESSAGES.network));
    renderModels();
    expect(await screen.findByText("The model catalog could not be loaded")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(cards()).toHaveLength(3));
  });

  it("loads one model's details from GET /models/{key}", async () => {
    vi.mocked(getModel).mockResolvedValue(all[1]);
    renderModels();
    await waitFor(() => expect(cards()).toHaveLength(3));

    fireEvent.click(screen.getByRole("button", { name: "Details for yolo11n" }));

    const details = await screen.findByRole("region", { name: "Model details" });
    await waitFor(() => expect(within(details).getByText("Enabled")).toBeTruthy());
    expect(getModel).toHaveBeenCalledWith("yolo11n", expect.any(AbortSignal));
  });
});
