import { describe, expect, it, vi } from "vitest";
import { cameraSupportProblem, describeCameraError, listCameras, openCamera } from "./liveCamera";
import { containRect, mapBox } from "./liveOverlay";
import { encodeFrame, liveMessage, liveSocketUrl, parseLiveMessage } from "./liveProtocol";

describe("live protocol", () => {
  it("prefixes frames with a big-endian unsigned 32-bit frame ID", () => {
    const jpeg = new Uint8Array([0xff, 0xd8, 0x01]).buffer;
    const message = new Uint8Array(encodeFrame(0x01020304, jpeg));
    expect([...message]).toEqual([1, 2, 3, 4, 0xff, 0xd8, 0x01]);
    expect(new DataView(encodeFrame(0xffffffff, jpeg)).getUint32(0, false)).toBe(0xffffffff);
  });

  it("parses every server message type", () => {
    expect(parseLiveMessage('{"type":"ready","sessionId":"s","modelKey":"yolo11n","maxFps":5,"maxFrameBytes":1,"maxInFlight":1}'))
      .toMatchObject({ type: "ready", maxFps: 5 });
    expect(parseLiveMessage(JSON.stringify({ type: "detections", frameId: 3, width: 640, height: 480,
      detections: [{ classId: 2, label: "car", confidence: 0.8, box: [1, 2, 3, 4] }], inferenceMs: 9, serverMs: 12 })))
      .toMatchObject({ type: "detections", frameId: 3, detections: [{ box: [1, 2, 3, 4] }] });
    expect(parseLiveMessage('{"type":"dropped","frameId":4,"reason":"BUSY"}')).toEqual(
      { type: "dropped", frameId: 4, reason: "BUSY" });
    expect(parseLiveMessage('{"type":"error","code":"X","message":"m","fatal":true}')).toMatchObject({ fatal: true });
    expect(parseLiveMessage('{"type":"stopped","reason":"IDLE_TIMEOUT","processedFrames":2,"droppedFrames":1}'))
      .toMatchObject({ reason: "IDLE_TIMEOUT", processedFrames: 2 });
  });

  it.each([
    "not json", "[]", '{"type":"unknown"}', '{"type":"detections","frameId":1}',
    '{"type":"detections","frameId":1,"width":1,"height":1,"inferenceMs":1,"detections":[{"classId":1,"label":"a","confidence":1,"box":[1,2]}]}',
    '{"type":"dropped","frameId":1,"reason":"OTHER"}',
  ])("rejects the malformed message %s", (raw) => {
    expect(parseLiveMessage(raw)).toBeNull();
  });

  it("builds a same-origin WebSocket URL that matches the page scheme", () => {
    expect(liveSocketUrl({ protocol: "http:", host: "localhost:5173" })).toBe("ws://localhost:5173/api/v1/live/ws");
    expect(liveSocketUrl({ protocol: "https:", host: "studio.lan" })).toBe("wss://studio.lan/api/v1/live/ws");
  });

  it("maps codes to user text and keeps the server text for unknown codes", () => {
    expect(liveMessage("MODEL_NOT_PREPARED", "x")).toMatch(/not prepared/);
    expect(liveMessage("SOMETHING_NEW", "Server explanation.")).toBe("Server explanation.");
  });
});

describe("live overlay geometry", () => {
  it("letterboxes the video inside its element like object-fit: contain", () => {
    expect(containRect(800, 400, 640, 480)).toEqual({ x: 400 - 266.6666666666667, y: 0, width: 533.3333333333334, height: 400 });
    expect(containRect(320, 480, 640, 480)).toEqual({ x: 0, y: 120, width: 320, height: 240 });
  });

  it("scales boxes from frame pixels to the displayed content", () => {
    const content = { x: 0, y: 120, width: 320, height: 240 };
    expect(mapBox([64, 48, 320, 240], 640, 480, content, false)).toEqual({ x: 32, y: 144, width: 128, height: 96 });
  });

  it("flips boxes horizontally when the preview is mirrored", () => {
    const content = { x: 0, y: 0, width: 640, height: 480 };
    expect(mapBox([0, 0, 100, 50], 640, 480, content, true)).toEqual({ x: 540, y: 0, width: 100, height: 50 });
  });
});

describe("live camera", () => {
  it.each([
    ["NotAllowedError", "DENIED"], ["SecurityError", "DENIED"], ["NotFoundError", "NOT_FOUND"],
    ["OverconstrainedError", "NOT_FOUND"], ["NotReadableError", "IN_USE"], ["AbortError", "IN_USE"],
    ["TypeError", "UNKNOWN"],
  ])("maps %s to %s", (name, code) => {
    expect(describeCameraError(new DOMException("x", name)).code).toBe(code);
  });

  it("requires a secure context and the media API", () => {
    expect(cameraSupportProblem({ isSecureContext: false, navigator: {} } as unknown as Window)?.code).toBe("INSECURE");
    expect(cameraSupportProblem({ isSecureContext: true, navigator: {} } as unknown as Window)?.code).toBe("UNSUPPORTED");
    expect(cameraSupportProblem({ isSecureContext: true,
      navigator: { mediaDevices: { getUserMedia: vi.fn() } } } as unknown as Window)).toBeNull();
  });

  it("lists only video inputs and names unlabeled cameras", async () => {
    const media = { enumerateDevices: vi.fn().mockResolvedValue([
      { kind: "audioinput", deviceId: "mic", label: "Mic" },
      { kind: "videoinput", deviceId: "a", label: "" },
      { kind: "videoinput", deviceId: "b", label: "USB Camera" },
    ]) } as unknown as MediaDevices;
    expect(await listCameras(media)).toEqual([{ deviceId: "a", label: "Camera 1" }, { deviceId: "b", label: "USB Camera" }]);
  });

  it("requests video only, about 640×480, and the chosen device", async () => {
    const getUserMedia = vi.fn().mockResolvedValue({});
    await openCamera("cam-2", { getUserMedia } as unknown as MediaDevices);
    expect(getUserMedia).toHaveBeenCalledWith({ audio: false, video: {
      deviceId: { exact: "cam-2" }, width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 15, max: 30 } } });
  });
});
