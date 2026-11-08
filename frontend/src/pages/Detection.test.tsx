import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { AxiosError } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, toApiError } from "../api/client";
import { createDetection } from "../api/detections";
import { getModelVersions, listModels } from "../api/models";
import { JOB_ID, model } from "../test/fixtures";
import { currentLocation, renderAt } from "../test/render";
import type { DetectionJobAccepted } from "../types/detections";
import type { ModelConfig } from "../types/models";
import { Detection } from "./Detection";

vi.mock("../api/models", () => ({ listModels: vi.fn(), getModelVersions: vi.fn() }));
vi.mock("../api/detections", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/detections")>()),
  createDetection: vi.fn(),
}));

const URL = "https://www.youtube.com/watch?v=abcdefghijk";
const catalog = [
  model({ modelKey: "yolov8n", version: "YOLOv8", modelSize: "n" }),
  model({ modelKey: "yolo11n", version: "YOLO11", modelSize: "n", enabled: true }),
  model({ modelKey: "yolo11s", version: "YOLO11", modelSize: "s" }),
  model({ modelKey: "yolo26s", version: "YOLO26", modelSize: "s" }),
];
const accepted: DetectionJobAccepted = {
  jobId: JOB_ID,
  status: "QUEUED",
  progress: 0,
  modelKey: "yolo11n",
  message: "Detection job accepted.",
};

function useCatalog(models: ModelConfig[]) {
  vi.mocked(listModels).mockResolvedValue({ models, total: models.length });
}
function problem(status: number, data: Record<string, unknown>): ApiError {
  return new ApiError("http", String(data.detail ?? "Request failed"), {
    status,
    problem: data,
  });
}

beforeEach(() => {
  vi.mocked(getModelVersions).mockResolvedValue({ versions: ["YOLOv8", "YOLO11", "YOLO12", "YOLO26"] });
  useCatalog(catalog);
  vi.mocked(createDetection).mockReset();
});
afterEach(cleanup);

const renderWorkspace = () => renderAt("/detection", "/detection", <Detection />);
const urlInput = () => screen.getByLabelText(/YouTube video URL/) as HTMLInputElement;
const submitButton = () => screen.getByRole("button", { name: /Start detection|Submitting/ });
const versionSelect = () => screen.getByLabelText("YOLO version") as HTMLSelectElement;
const confidenceInput = () => screen.getByLabelText("Confidence threshold value") as HTMLInputElement;

async function ready() {
  renderWorkspace();
  await screen.findByLabelText("YOLO version");
}

describe("Detection workspace", () => {
  it("loads the real catalog and defaults to the first enabled model", async () => {
    renderWorkspace();
    expect(screen.getByText("Loading the model catalog")).toBeTruthy();
    await screen.findByLabelText("YOLO version");
    expect(versionSelect().value).toBe("YOLO11");
    expect(
      [...versionSelect().options].map((option) => option.textContent),
    ).toEqual(["YOLOv8 (none enabled)", "YOLO11 (1 enabled)", "YOLO26 (none enabled)"]);
    expect((screen.getByRole("radio", { name: /Nano/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/is enabled for detection/)).toBeTruthy();
    expect(urlInput().value).toBe("");
    expect(confidenceInput().value).toBe("0.25");
    expect((screen.getByLabelText("Inference image size") as HTMLSelectElement).value).toBe("640");
    expect(screen.getByText("5 of 80 selected")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Vehicles (default)" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("shows a catalog error with a retry action", async () => {
    vi.mocked(listModels)
      .mockRejectedValueOnce(toApiError(new AxiosError("Network Error", "ERR_NETWORK")))
      .mockResolvedValueOnce({ models: catalog, total: catalog.length });
    renderWorkspace();
    expect(await screen.findByText("The model catalog could not be loaded")).toBeTruthy();
    expect((submitButton() as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("YOLO version")).toBeTruthy();
  });

  it("explains an empty catalog and blocks submission", async () => {
    useCatalog([]);
    renderWorkspace();
    expect(await screen.findByText("No models are registered.")).toBeTruthy();
    expect((submitButton() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("A registered model is needed before submitting.")).toBeTruthy();
  });

  it("never submits when no model is enabled", async () => {
    useCatalog(catalog.map((item) => ({ ...item, enabled: false })));
    await ready();
    expect(screen.getByText(/No detection models are enabled/)).toBeTruthy();
    expect(versionSelect().value).toBe("YOLOv8");
    fireEvent.change(urlInput(), { target: { value: URL } });
    fireEvent.click(submitButton());
    expect(screen.getByText("1 item to fix before submitting")).toBeTruthy();
    expect(createDetection).not.toHaveBeenCalled();
  });

  it("switches versions through real catalog records and blocks disabled models", async () => {
    await ready();
    fireEvent.change(versionSelect(), { target: { value: "YOLO26" } });
    const small = screen.getByRole("radio", { name: /Small/ }) as HTMLInputElement;
    expect(small.checked).toBe(true);
    expect(screen.queryByRole("radio", { name: /Nano/ })).toBeNull();
    expect(screen.getByText(/is disabled and cannot be submitted. An administrator/)).toBeTruthy();
    expect(screen.getByText("The selected model is disabled and cannot be submitted.")).toBeTruthy();

    fireEvent.change(urlInput(), { target: { value: URL } });
    fireEvent.click(submitButton());
    expect(createDetection).not.toHaveBeenCalled();

    fireEvent.change(versionSelect(), { target: { value: "YOLO11" } });
    expect((screen.getByRole("radio", { name: /Small/ }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: /Nano/ }));
    expect(screen.getByText("Ready to submit")).toBeTruthy();
  });

  it("validates the URL on blur without being stricter than the backend", async () => {
    await ready();
    fireEvent.change(urlInput(), { target: { value: "https://www.youtube.com/playlist?list=PLabc" } });
    expect(screen.queryByText(/Playlists are not supported/)).toBeNull();
    fireEvent.blur(urlInput());
    expect(screen.getByText("Playlists are not supported. Use a single video URL.")).toBeTruthy();
    expect(urlInput().getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(urlInput(), { target: { value: "https://youtu.be/abcdefghijk?t=10" } });
    expect(screen.queryByText(/Playlists are not supported/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Clear video URL" }));
    expect(urlInput().value).toBe("");
  });

  it("selects classes with presets, search, chips, and checkboxes", async () => {
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByText("0 of 80 selected")).toBeTruthy();
    expect(screen.getByText("Select at least one object class.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "All 80 classes" }));
    expect(screen.getByText("80 of 80 selected")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Vehicles (default)" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove bus" }));
    expect(screen.getByText("4 of 80 selected")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Search object classes"), { target: { value: "traffic" } });
    const grid = screen.getByRole("group", { name: "COCO object classes" });
    expect(within(grid).getAllByRole("checkbox")).toHaveLength(1);
    fireEvent.click(within(grid).getByRole("checkbox", { name: /Traffic light/ }));
    expect(screen.getByText("5 of 80 selected")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Vehicles (default)" }).getAttribute("aria-pressed")).toBe("false");

    fireEvent.change(screen.getByLabelText("Search object classes"), { target: { value: "unicorn" } });
    expect(screen.getByText(/No class matches/)).toBeTruthy();
  });

  it("keeps the confidence slider and number in sync and validates the value", async () => {
    await ready();
    const slider = screen.getByLabelText("Confidence threshold") as HTMLInputElement;
    fireEvent.change(slider, { target: { value: "0.6" } });
    expect(confidenceInput().value).toBe("0.60");
    fireEvent.change(confidenceInput(), { target: { value: "1.5" } });
    expect(screen.getByText("Enter a value from 0 to 1 with at most three decimals.")).toBeTruthy();
    expect(screen.getByText("Invalid")).toBeTruthy();
    fireEvent.change(confidenceInput(), { target: { value: "0.125" } });
    expect(screen.queryByText(/at most three decimals/)).toBeNull();
    expect(slider.value).toBe("0.125");
  });

  it("submits exactly the public payload once and opens the job page", async () => {
    let resolve: (value: DetectionJobAccepted) => void = () => undefined;
    vi.mocked(createDetection).mockReturnValueOnce(new Promise((done) => (resolve = done)));
    const { container } = renderWorkspace();
    await screen.findByLabelText("YOLO version");
    fireEvent.change(urlInput(), { target: { value: ` ${URL} ` } });
    fireEvent.change(confidenceInput(), { target: { value: "0.4" } });
    fireEvent.change(screen.getByLabelText("Inference image size"), { target: { value: "960" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Person/ }));

    fireEvent.click(submitButton());
    fireEvent.click(submitButton());
    fireEvent.submit(urlInput().form!);
    expect(createDetection).toHaveBeenCalledTimes(1);
    expect(vi.mocked(createDetection).mock.calls[0][0]).toEqual({
      videoUrl: URL,
      modelKey: "yolo11n",
      confidence: 0.4,
      imageSize: 960,
      classes: [0, 1, 2, 3, 5, 7],
    });
    expect(await screen.findByText("Submitting the detection job…")).toBeTruthy();
    expect((submitButton() as HTMLButtonElement).disabled).toBe(true);
    expect(urlInput().disabled).toBe(true);

    resolve(accepted);
    await waitFor(() => expect(currentLocation(container)).toBe(`/detections/${JOB_ID}`));
    expect(createDetection).toHaveBeenCalledTimes(1);
  });

  it("does not call the API for an invalid form and focuses the first invalid field", async () => {
    await ready();
    fireEvent.click(submitButton());
    expect(createDetection).not.toHaveBeenCalled();
    expect(screen.getByText("Enter a YouTube video URL.")).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(urlInput()));
  });

  it("shows backend field errors and preserves the entered values", async () => {
    vi.mocked(createDetection).mockRejectedValueOnce(
      problem(400, {
        code: "INVALID_DETECTION_REQUEST",
        detail: "Detection request validation failed.",
        errors: { videoUrl: "must identify one valid YouTube video", extra: "is not supported" },
      }),
    );
    await ready();
    fireEvent.change(urlInput(), { target: { value: URL } });
    fireEvent.click(submitButton());
    expect(await screen.findByText("Some settings were rejected")).toBeTruthy();
    expect(screen.getByText("Rejected by the server: must identify one valid YouTube video.")).toBeTruthy();
    expect(screen.getByText(/extra: is not supported\./)).toBeTruthy();
    expect(urlInput().value).toBe(URL);
    expect((submitButton() as HTMLButtonElement).disabled).toBe(false);

    fireEvent.change(urlInput(), { target: { value: "https://youtu.be/bcdefghijkl" } });
    expect(screen.queryByText(/Rejected by the server/)).toBeNull();
  });

  it("explains MODEL_DISABLED and reloads the catalog on request", async () => {
    vi.mocked(createDetection).mockRejectedValueOnce(
      problem(409, { code: "MODEL_DISABLED", detail: "Model yolo11n is disabled." }),
    );
    await ready();
    fireEvent.change(urlInput(), { target: { value: URL } });
    fireEvent.click(submitButton());
    expect(await screen.findByText("The model is disabled")).toBeTruthy();
    expect(screen.getByText(/No job was created/)).toBeTruthy();
    useCatalog(catalog.map((item) => ({ ...item, enabled: false })));
    fireEvent.click(screen.getByRole("button", { name: "Reload models" }));
    expect(await screen.findByText(/No detection models are enabled/)).toBeTruthy();
    expect(urlInput().value).toBe(URL);
  });

  it("treats a network failure as ambiguous and never retries automatically", async () => {
    vi.mocked(createDetection).mockRejectedValueOnce(
      toApiError(new AxiosError("Network Error", "ERR_NETWORK")),
    );
    await ready();
    fireEvent.change(urlInput(), { target: { value: URL } });
    fireEvent.click(submitButton());
    expect(await screen.findByText("The submission result is unknown")).toBeTruthy();
    expect(screen.getByText(/Check Detection History before submitting again/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open detection history" }).getAttribute("href")).toBe("/history");
    expect(createDetection).toHaveBeenCalledTimes(1);
    expect(urlInput().value).toBe(URL);
  });

  it("treats a 5xx without a problem code as ambiguous", async () => {
    vi.mocked(createDetection).mockRejectedValueOnce(new ApiError("http", "Bad gateway", { status: 502 }));
    await ready();
    fireEvent.change(urlInput(), { target: { value: URL } });
    fireEvent.click(submitButton());
    expect(await screen.findByText("The submission result is unknown")).toBeTruthy();
  });

  it("reports an unrecognised 4xx as a definite rejection", async () => {
    vi.mocked(createDetection).mockRejectedValueOnce(
      new ApiError("http", "The request failed (HTTP 403).", { status: 403 }),
    );
    await ready();
    fireEvent.change(urlInput(), { target: { value: URL } });
    fireEvent.click(submitButton());
    expect(await screen.findByText("The request was rejected")).toBeTruthy();
    expect(screen.getByText("The request failed (HTTP 403). No job was created.")).toBeTruthy();
    expect(screen.queryByText("The submission result is unknown")).toBeNull();
  });

  it("treats an unreadable success response as ambiguous", async () => {
    vi.mocked(createDetection).mockRejectedValueOnce(
      new ApiError("invalid-response", "The backend returned an unexpected response."),
    );
    await ready();
    fireEvent.change(urlInput(), { target: { value: URL } });
    fireEvent.click(submitButton());
    expect(await screen.findByText("The submission result is unknown")).toBeTruthy();
  });

  it("reports SERVICE_UNAVAILABLE as not accepted", async () => {
    vi.mocked(createDetection).mockRejectedValueOnce(
      problem(503, { code: "SERVICE_UNAVAILABLE", detail: "Unavailable." }),
    );
    await ready();
    fireEvent.change(urlInput(), { target: { value: URL } });
    fireEvent.click(submitButton());
    expect(await screen.findByText("The service is temporarily unavailable")).toBeTruthy();
    expect(screen.getByText(/nothing was created/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open detection history" })).toBeNull();
  });
});
