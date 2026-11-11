import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listModels } from "../api/models";
import type { CapturedFrame, LiveDependencies } from "../hooks/useLiveDetection";
import { model } from "../test/fixtures";
import { renderAt } from "../test/render";
import { LiveDetection } from "./LiveDetection";

vi.mock("../api/models", () => ({ listModels: vi.fn(), getModelVersions: vi.fn(), getModel: vi.fn() }));

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState = 0;
  binaryType = "blob";
  sent: (string | ArrayBuffer)[] = [];
  frameTimes: number[] = [];
  closed: { code?: number } | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(data);
    if (data instanceof ArrayBuffer) this.frameTimes.push(performance.now());
  }

  close(code?: number) {
    this.closed = { code };
    this.readyState = 3;
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  serverSends(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  serverCloses() {
    this.readyState = 3;
    this.onclose?.();
  }

  frames(): number[] {
    return this.sent.filter((item): item is ArrayBuffer => item instanceof ArrayBuffer)
      .map((buffer) => new DataView(buffer).getUint32(0, false));
  }

  texts(): Record<string, unknown>[] {
    return this.sent.filter((item): item is string => typeof item === "string").map((item) => JSON.parse(item));
  }
}

function fakeTrack() {
  const listeners: Record<string, () => void> = {};
  return {
    stop: vi.fn(),
    addEventListener: vi.fn((name: string, listener: () => void) => {
      listeners[name] = listener;
    }),
    end: () => listeners.ended?.(),
  };
}

let track: ReturnType<typeof fakeTrack>;
let getUserMedia: ReturnType<typeof vi.fn>;
let captureFrame: ReturnType<typeof vi.fn>;
let context: Record<string, ReturnType<typeof vi.fn>>;

function media(): MediaDevices {
  return {
    getUserMedia,
    enumerateDevices: vi.fn().mockResolvedValue([
      { kind: "videoinput", deviceId: "cam-1", label: "Integrated Webcam" },
      { kind: "videoinput", deviceId: "cam-2", label: "USB Camera" },
    ]),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaDevices;
}

const dependencies = (): Partial<LiveDependencies> => ({
  createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
  captureFrame: captureFrame as unknown as LiveDependencies["captureFrame"],
  media,
});

beforeEach(() => {
  FakeSocket.instances = [];
  track = fakeTrack();
  getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [track], getVideoTracks: () => [track] });
  captureFrame = vi.fn(async (): Promise<CapturedFrame> => ({ buffer: new ArrayBuffer(16), width: 640, height: 480 }));
  context = {
    setTransform: vi.fn(), clearRect: vi.fn(), strokeRect: vi.fn(), fillRect: vi.fn(), fillText: vi.fn(),
    measureText: vi.fn(() => ({ width: 40 })),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  vi.mocked(listModels).mockResolvedValue({
    total: 3,
    models: [
      model({ modelKey: "yolov8n", version: "YOLOv8", modelSize: "n", enabled: false }),
      model({ modelKey: "yolo11n", version: "YOLO11", modelSize: "n", enabled: true }),
      model({ modelKey: "yolo11s", version: "YOLO11", modelSize: "s", enabled: true }),
    ],
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const renderLive = () => renderAt("/live", "/live", <LiveDetection dependencies={dependencies()} />);
const startButton = () => screen.getByRole("button", { name: /Start Live Detection|Starting/ });
const stopButton = () => screen.getByRole("button", { name: "Stop" });

async function startSession() {
  const view = renderLive();
  await waitFor(() => expect((startButton() as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(startButton());
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  const socket = FakeSocket.instances[0];
  act(() => socket.open());
  act(() => socket.serverSends({ type: "ready", sessionId: "s-1", modelKey: "yolo11n", maxFps: 5,
    maxFrameBytes: 524288, maxInFlight: 1 }));
  await waitFor(() => expect(socket.frames()).toHaveLength(1));
  return { view, socket };
}

const detections = (frameId: number, boxes = 1) => ({
  type: "detections", frameId, width: 640, height: 480, inferenceMs: 30, serverMs: 41,
  detections: Array.from({ length: boxes }, () => ({ classId: 2, label: "car", confidence: 0.87,
    box: [120, 85, 310, 260] })),
});

describe("Live Detection page", () => {
  it("offers only Nano detection models and never selects a disabled one", async () => {
    renderLive();
    const select = (await screen.findByLabelText("AI model")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("yolo11n"));
    const options = within(select).getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((option) => option.value)).toEqual(["yolov8n", "yolo11n"]);
    expect(options[0].disabled).toBe(true);
    expect(options[0].textContent).toContain("disabled");
    expect(screen.getByText(/Enabled does not mean prepared/)).toBeTruthy();
  });

  it("cannot start without an enabled Nano model", async () => {
    vi.mocked(listModels).mockResolvedValue({ total: 1, models: [model({ modelKey: "yolov8n", modelSize: "n" })] });
    renderLive();
    expect(await screen.findByText("No enabled Nano detection model is available.")).toBeTruthy();
    expect((startButton() as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps the camera off until the user starts", async () => {
    renderLive();
    await screen.findByLabelText("AI model");
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(screen.getByText(/The camera is off/)).toBeTruthy();
    expect(screen.getByText("Camera off")).toBeTruthy();
    expect(FakeSocket.instances).toHaveLength(0);
  });

  it.each([
    ["NotAllowedError", /permission was denied/],
    ["NotFoundError", /No camera was found/],
    ["NotReadableError", /in use by another application/],
  ])("explains a camera failure (%s) and opens no connection", async (name, text) => {
    getUserMedia.mockRejectedValueOnce(new DOMException("x", name));
    renderLive();
    await waitFor(() => expect((startButton() as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(startButton());
    expect(await screen.findByText(text)).toBeTruthy();
    expect(FakeSocket.instances).toHaveLength(0);
    expect((startButton() as HTMLButtonElement).disabled).toBe(false);
  });

  it("explains that cameras need a secure context", async () => {
    Object.defineProperty(window, "isSecureContext", { value: false, configurable: true });
    renderLive();
    await waitFor(() => expect((startButton() as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(startButton());
    expect(await screen.findByText(/needs a secure connection/)).toBeTruthy();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("requests video only from the selected camera and starts a session with the settings", async () => {
    renderLive();
    const camera = (await screen.findByLabelText("Camera")) as HTMLSelectElement;
    await waitFor(() => expect(within(camera).getAllByRole("option")).toHaveLength(2));
    fireEvent.change(camera, { target: { value: "cam-2" } });
    await waitFor(() => expect((startButton() as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(startButton());
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));

    expect(getUserMedia.mock.calls[0][0]).toMatchObject({ audio: false, video: { deviceId: { exact: "cam-2" } } });
    const socket = FakeSocket.instances[0];
    expect(socket.url).toBe(`ws://${window.location.host}/api/v1/live/ws`);
    act(() => socket.open());
    expect(socket.texts()[0]).toEqual({ type: "start", version: 1, modelKey: "yolo11n", confidence: 0.25,
      imageSize: 416, classes: [1, 2, 3, 5, 7] });
    expect(screen.getByText(/Connecting to the detector/)).toBeTruthy();
  });

  it("sends one frame at a time and draws the boxes it receives", async () => {
    const { socket } = await startSession();
    expect(screen.getByText("Detecting live")).toBeTruthy();
    // No second frame while the first is in flight.
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(socket.frames()).toEqual([1]);

    act(() => socket.serverSends(detections(1)));
    expect(context.strokeRect).toHaveBeenCalledTimes(1);
    expect(context.fillText).toHaveBeenCalledWith("Car 87%", expect.any(Number), expect.any(Number));
    await waitFor(() => expect(socket.frames()).toEqual([1, 2]));
  });

  it("throttles frames to the session rate even when results come back instantly", async () => {
    const { socket } = await startSession();
    for (let frame = 1; frame <= 3; frame += 1) {
      act(() => socket.serverSends(detections(frame)));
      await waitFor(() => expect(socket.frames()).toHaveLength(frame + 1));
    }
    // maxFps 5 → at least ~200 ms between consecutive frames (small tolerance for timers).
    const gaps = socket.frameTimes.slice(1).map((time, index) => time - socket.frameTimes[index]);
    expect(gaps).toHaveLength(3);
    gaps.forEach((gap) => expect(gap).toBeGreaterThanOrEqual(190));
    expect(captureFrame).toHaveBeenCalledTimes(4);
  });

  it("honours a lower server frame rate", async () => {
    renderLive();
    await waitFor(() => expect((startButton() as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(startButton());
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
    const socket = FakeSocket.instances[0];
    act(() => socket.open());
    act(() => socket.serverSends({ type: "ready", sessionId: "s", modelKey: "yolo11n", maxFps: 2,
      maxFrameBytes: 524288, maxInFlight: 1 }));
    await waitFor(() => expect(socket.frames()).toHaveLength(1));
    act(() => socket.serverSends(detections(1)));
    await waitFor(() => expect(socket.frames()).toHaveLength(2), { timeout: 2000 });
    expect(socket.frameTimes[1] - socket.frameTimes[0]).toBeGreaterThanOrEqual(480);
  });

  it("ignores results for frames it is not waiting for", async () => {
    const { socket } = await startSession();
    act(() => socket.serverSends(detections(99)));
    expect(context.strokeRect).not.toHaveBeenCalled();
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(socket.frames()).toEqual([1]);
  });

  it("handles empty results and dropped frames without stalling", async () => {
    const { socket } = await startSession();
    act(() => socket.serverSends(detections(1, 0)));
    expect(context.strokeRect).not.toHaveBeenCalled();
    expect(context.clearRect).toHaveBeenCalled();
    await waitFor(() => expect(socket.frames()).toHaveLength(2));
    act(() => socket.serverSends({ type: "dropped", frameId: 2, reason: "RATE_LIMITED" }));
    await waitFor(() => expect(socket.frames()).toHaveLength(3));
  });

  it("shows measured metrics", async () => {
    const { socket } = await startSession();
    act(() => socket.serverSends(detections(1, 3)));
    await waitFor(() => expect(socket.frames()).toHaveLength(2));
    act(() => socket.serverSends(detections(2, 3)));
    const metrics = screen.getByLabelText("Live detection metrics");
    await waitFor(() => expect(within(metrics).getByText("Inference").nextElementSibling?.textContent).toBe("30 ms"), { timeout: 2000 });
    expect(within(metrics).getByText("Frames").nextElementSibling?.textContent).toBe("2");
    expect(within(metrics).getByText("Objects").nextElementSibling?.textContent).toBe("3");
    expect(within(metrics).getByText("Latency").nextElementSibling?.textContent).toMatch(/^\d+ ms$/);
  });

  it("shows a non-fatal frame error and keeps going", async () => {
    const { socket } = await startSession();
    act(() => socket.serverSends({ type: "error", code: "INFERENCE_TIMEOUT", message: "slow", fatal: false, frameId: 1 }));
    expect(await screen.findByText(/responding slowly/)).toBeTruthy();
    await waitFor(() => expect(socket.frames()).toHaveLength(2));
    expect(track.stop).not.toHaveBeenCalled();
  });

  it("ends the session on a fatal error and releases the camera", async () => {
    const { socket } = await startSession();
    act(() => socket.serverSends({ type: "error", code: "MODEL_NOT_PREPARED", message: "x", fatal: true }));
    expect(await screen.findByText(/weights are not prepared/)).toBeTruthy();
    expect(track.stop).toHaveBeenCalled();
    expect(socket.closed).not.toBeNull();
    expect(screen.getByText("Camera off")).toBeTruthy();
  });

  it("stops cleanly: tells the server, closes the socket, and releases the camera", async () => {
    const { socket } = await startSession();
    fireEvent.click(stopButton());
    expect(socket.texts().at(-1)).toEqual({ type: "stop" });
    expect(socket.closed?.code).toBe(1000);
    expect(track.stop).toHaveBeenCalled();
    expect((screen.getByLabelText("Live camera preview") as HTMLVideoElement).srcObject).toBeNull();
    expect(screen.getByText("Camera off")).toBeTruthy();
    const framesAtStop = socket.frames().length;
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(socket.frames()).toHaveLength(framesAtStop);
  });

  it("can start again after stopping", async () => {
    await startSession();
    fireEvent.click(stopButton());
    await waitFor(() => expect((startButton() as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(startButton());
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(2));
    expect(getUserMedia).toHaveBeenCalledTimes(2);
  });

  it("reports a lost connection and releases the camera", async () => {
    const { socket } = await startSession();
    act(() => socket.serverCloses());
    expect(await screen.findByText(/connection to the live detection server was lost/)).toBeTruthy();
    expect(track.stop).toHaveBeenCalled();
  });

  it("stops when the camera is disconnected", async () => {
    const { socket } = await startSession();
    act(() => track.end());
    expect(await screen.findByText("The camera was disconnected.")).toBeTruthy();
    expect(socket.closed).not.toBeNull();
  });

  it("shows why the server ended the session", async () => {
    const { socket } = await startSession();
    act(() => socket.serverSends({ type: "stopped", reason: "IDLE_TIMEOUT", processedFrames: 0, droppedFrames: 0 }));
    expect(await screen.findByText(/no frames were sent for a while/)).toBeTruthy();
  });

  it("releases everything when the page is left", async () => {
    const { view, socket } = await startSession();
    view.unmount();
    expect(track.stop).toHaveBeenCalled();
    expect(socket.closed?.code).toBe(1000);
  });

  it("pauses sending while the tab is hidden", async () => {
    const { socket } = await startSession();
    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    act(() => socket.serverSends(detections(1)));
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(socket.frames()).toEqual([1]);
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
    await waitFor(() => expect(socket.frames()).toHaveLength(2), { timeout: 2000 });
  });

  it("locks the settings while a session runs", async () => {
    await startSession();
    expect((screen.getByLabelText("AI model") as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByLabelText("Camera") as HTMLSelectElement).disabled).toBe(true);
    expect((startButton() as HTMLButtonElement).disabled).toBe(true);
  });
});
