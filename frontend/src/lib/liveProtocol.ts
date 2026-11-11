import { API_BASE_URL } from "../api/client";

/**
 * Live Detection WebSocket protocol, version 1 (docs/live-detection-architecture.md).
 * Control and result messages are JSON text; camera frames are binary:
 * a 4-byte big-endian unsigned frame ID followed by the JPEG bytes.
 */
export const LIVE_PROTOCOL_VERSION = 1;
export const LIVE_IMAGE_SIZES = [320, 416, 640] as const;
export const LIVE_DEFAULT_IMAGE_SIZE = 416;
/** Frames are scaled down to at most this width before encoding. */
export const LIVE_CAPTURE_WIDTH = 640;
export const LIVE_JPEG_QUALITY = 0.7;
/** Client-side ceiling; the server's `maxFps` from `ready` can only lower it. */
export const LIVE_TARGET_FPS = 5;
export const MAX_FRAME_ID = 0xffffffff;

export interface LiveStartRequest {
  type: "start";
  version: number;
  modelKey: string;
  confidence: number;
  imageSize: number;
  classes: number[];
}

export interface LiveDetection {
  classId: number;
  label: string;
  confidence: number;
  /** [x1, y1, x2, y2] in pixels of the submitted frame. */
  box: [number, number, number, number];
}

export interface LiveReady {
  type: "ready";
  sessionId: string;
  modelKey: string;
  maxFps: number;
  maxFrameBytes: number;
  maxInFlight: number;
}

export interface LiveDetections {
  type: "detections";
  frameId: number;
  width: number;
  height: number;
  detections: LiveDetection[];
  inferenceMs: number;
  serverMs: number;
}

export interface LiveDropped {
  type: "dropped";
  frameId: number;
  reason: "BUSY" | "RATE_LIMITED";
}

export interface LiveError {
  type: "error";
  code: string;
  message: string;
  fatal: boolean;
  frameId?: number;
}

export interface LiveStopped {
  type: "stopped";
  reason: string;
  processedFrames: number;
  droppedFrames: number;
}

export type LiveServerMessage = LiveReady | LiveDetections | LiveDropped | LiveError | LiveStopped;

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const isString = (value: unknown): value is string => typeof value === "string";

function toDetection(value: unknown): LiveDetection | null {
  if (!isRecord(value) || !isNumber(value.classId) || !isString(value.label) || !isNumber(value.confidence)) {
    return null;
  }
  const box = value.box;
  if (!Array.isArray(box) || box.length !== 4 || !box.every(isNumber)) return null;
  return {
    classId: value.classId,
    label: value.label,
    confidence: value.confidence,
    box: [box[0], box[1], box[2], box[3]],
  };
}

/** Runtime-checked parse of a server text message; anything unexpected yields null. */
export function parseLiveMessage(raw: string): LiveServerMessage | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(data)) return null;
  switch (data.type) {
    case "ready":
      return isString(data.sessionId) && isString(data.modelKey) && isNumber(data.maxFps) &&
        isNumber(data.maxFrameBytes) && isNumber(data.maxInFlight)
        ? { type: "ready", sessionId: data.sessionId, modelKey: data.modelKey, maxFps: data.maxFps,
            maxFrameBytes: data.maxFrameBytes, maxInFlight: data.maxInFlight }
        : null;
    case "detections": {
      if (!isNumber(data.frameId) || !isNumber(data.width) || !isNumber(data.height) ||
          !Array.isArray(data.detections) || !isNumber(data.inferenceMs)) {
        return null;
      }
      const detections = data.detections.map(toDetection);
      if (detections.some((item) => item === null)) return null;
      return { type: "detections", frameId: data.frameId, width: data.width, height: data.height,
        detections: detections as LiveDetection[], inferenceMs: data.inferenceMs,
        serverMs: isNumber(data.serverMs) ? data.serverMs : 0 };
    }
    case "dropped":
      return isNumber(data.frameId) && (data.reason === "BUSY" || data.reason === "RATE_LIMITED")
        ? { type: "dropped", frameId: data.frameId, reason: data.reason }
        : null;
    case "error":
      return isString(data.code) && isString(data.message)
        ? { type: "error", code: data.code, message: data.message, fatal: data.fatal === true,
            frameId: isNumber(data.frameId) ? data.frameId : undefined }
        : null;
    case "stopped":
      return isString(data.reason)
        ? { type: "stopped", reason: data.reason,
            processedFrames: isNumber(data.processedFrames) ? data.processedFrames : 0,
            droppedFrames: isNumber(data.droppedFrames) ? data.droppedFrames : 0 }
        : null;
    default:
      return null;
  }
}

/** Binary frame message: uint32 big-endian frame ID, then the JPEG bytes. */
export function encodeFrame(frameId: number, jpeg: ArrayBuffer): ArrayBuffer {
  const message = new Uint8Array(4 + jpeg.byteLength);
  new DataView(message.buffer).setUint32(0, frameId >>> 0, false);
  message.set(new Uint8Array(jpeg), 4);
  return message.buffer;
}

/** Same-origin WebSocket URL, so it goes through the Vite or nginx proxy like the REST API. */
export function liveSocketUrl(location: Pick<Location, "protocol" | "host"> = window.location): string {
  if (/^https?:\/\//.test(API_BASE_URL)) {
    return `${API_BASE_URL.replace(/^http/, "ws")}/live/ws`;
  }
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}${API_BASE_URL}/live/ws`;
}

const MESSAGES: Record<string, string> = {
  MODEL_NOT_FOUND: "The selected model is not registered.",
  MODEL_DISABLED: "The selected model is disabled. An administrator must enable it first.",
  MODEL_NOT_SUPPORTED: "Live Detection supports only lightweight (Nano) detection models.",
  MODEL_NOT_PREPARED:
    "The model is enabled but its weights are not prepared on the server. An administrator must prepare it first.",
  MODEL_LOAD_FAILED: "The live worker could not load the model.",
  SESSION_LIMIT_REACHED: "Another live session is already running. Stop it or try again later.",
  WORKER_UNAVAILABLE: "The live detection worker is not reachable. Check that the ai-live-worker service is running.",
  INFERENCE_TIMEOUT: "The live worker is responding slowly.",
  INFERENCE_FAILED: "Detection failed for a frame.",
  INVALID_SETTINGS: "The live detection settings were rejected.",
  IDLE_TIMEOUT: "The session ended because no frames were sent for a while.",
  MAX_DURATION: "The session reached its maximum duration.",
  SERVER_SHUTDOWN: "The server is shutting down.",
};

/** User-facing text for a server code; falls back to the server's own client-safe message. */
export function liveMessage(code: string, fallback: string): string {
  return MESSAGES[code] ?? fallback;
}
