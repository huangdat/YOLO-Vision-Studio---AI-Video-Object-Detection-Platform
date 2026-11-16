import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import {
  cameraSupportProblem,
  describeCameraError,
  listCameras,
  openCamera,
  stopStream,
  type CameraDevice,
} from "../lib/liveCamera";
import { clearOverlay, drawDetections, TrackTrails } from "../lib/liveOverlay";
import {
  encodeFrame,
  LIVE_CAPTURE_WIDTH,
  LIVE_JPEG_QUALITY,
  LIVE_PROTOCOL_VERSION,
  LIVE_TARGET_FPS,
  liveMessage,
  liveSocketUrl,
  MAX_FRAME_ID,
  parseLiveMessage,
  type LiveDetection,
  type LiveDetections,
  type LiveServerMessage,
  type LiveTrackingMode,
} from "../lib/liveProtocol";
import { DEFAULT_TRACKER_CONFIG } from "../lib/tracking/byteTracker";
import { createTrackerWorker, LiveTrackerClient, type WorkerLike } from "../lib/tracking/trackerClient";

export type LivePhase = "idle" | "starting" | "running";
export type LiveConnectionState = "idle" | "connecting" | "live";

export interface LiveSettings {
  modelKey: string;
  confidence: number;
  imageSize: number;
  classes: number[];
  /** Run ByteTrack for this session. */
  tracking: boolean;
  /** Where ByteTrack runs: CLIENT (browser Web Worker) or SERVER (live worker, legacy). */
  trackingMode?: LiveTrackingMode;
}

export interface LiveMetrics {
  /** Results per second over the last few seconds (processed, not captured). */
  fps: number | null;
  /** Browser-measured time from sending a frame to drawing its result. */
  latencyMs: number | null;
  /** YOLO time reported by the worker for the last frame. */
  inferenceMs: number | null;
  processed: number;
  dropped: number;
  detections: number;
  /** Active tracks for the last frame; null unless tracking is on. */
  activeTracks: number | null;
  /** Frames sent to the server per second (not camera FPS). */
  submittedFps: number | null;
  /** Time from sending a frame to receiving its detections (network + server + YOLO). */
  roundTripMs: number | null;
  /** ByteTrack time in the browser's Web Worker for the last frame (CLIENT tracking only). */
  trackingMs: number | null;
  /** Device and precision the worker reported for the last frame. */
  device: string | null;
  precision: string | null;
}

export interface LiveNotice {
  tone: "error" | "warning" | "info";
  text: string;
}

export interface CapturedFrame {
  buffer: ArrayBuffer;
  width: number;
  height: number;
}

export interface LiveDependencies {
  createSocket: (url: string) => WebSocket;
  captureFrame: (video: HTMLVideoElement) => Promise<CapturedFrame | null>;
  now: () => number;
  media: () => MediaDevices | undefined;
  /** Creates the tracking Web Worker for CLIENT tracking sessions. */
  trackerWorker: () => WorkerLike;
}

/** Captures the current video frame, scaled to at most LIVE_CAPTURE_WIDTH, as JPEG. One canvas is reused. */
export function createFrameCapturer(maxWidth = LIVE_CAPTURE_WIDTH, quality = LIVE_JPEG_QUALITY) {
  let canvas: HTMLCanvasElement | null = null;
  return async (video: HTMLVideoElement): Promise<CapturedFrame | null> => {
    const sourceWidth = video.videoWidth;
    const sourceHeight = video.videoHeight;
    if (!sourceWidth || !sourceHeight) return null;
    const scale = Math.min(1, maxWidth / sourceWidth);
    const width = Math.round(sourceWidth * scale);
    const height = Math.round(sourceHeight * scale);
    canvas ??= document.createElement("canvas");
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const context = canvas.getContext("2d");
    if (!context) return null;
    context.drawImage(video, 0, 0, width, height);
    const target = canvas;
    const blob = await new Promise<Blob | null>((resolve) => target.toBlob(resolve, "image/jpeg", quality));
    return blob ? { buffer: await blob.arrayBuffer(), width, height } : null;
  };
}

const defaultDependencies = (): LiveDependencies => ({
  createSocket: (url) => new WebSocket(url),
  captureFrame: createFrameCapturer(),
  now: () => performance.now(),
  media: () => (typeof navigator === "undefined" ? undefined : navigator.mediaDevices),
  trackerWorker: createTrackerWorker,
});

interface Run {
  stopped: boolean;
  socket: WebSocket | null;
  stream: MediaStream | null;
  frameId: number;
  inFlight: number | null;
  sentAt: number;
  lastSentAt: number;
  capturing: boolean;
  intervalMs: number;
  timer: ReturnType<typeof setTimeout> | null;
  resultTimes: number[];
  processed: number;
  dropped: number;
  latencyMs: number | null;
  inferenceMs: number | null;
  detections: number;
  activeTracks: number | null;
  /** Created per session from the server's ready message; discarded when the session ends. */
  trails: TrackTrails | null;
  /** Browser ByteTrack for a CLIENT tracking session; closed when the session ends. */
  tracker: LiveTrackerClient | null;
  clientTracking: boolean;
  confidence: number;
  sendTimes: number[];
  roundTripMs: number | null;
  trackingMs: number | null;
  device: string | null;
  precision: string | null;
  lastDrawnFrameId: number;
}

const EMPTY_METRICS: LiveMetrics = {
  fps: null, latencyMs: null, inferenceMs: null, processed: 0, dropped: 0, detections: 0, activeTracks: null,
  submittedFps: null, roundTripMs: null, trackingMs: null, device: null, precision: null,
};

const rate = (times: number[], now: number): [number[], number | null] => {
  const recent = times.filter((time) => now - time <= 3000);
  const span = recent.length > 1 ? (recent[recent.length - 1] - recent[0]) / 1000 : 0;
  return [recent, span > 0 ? (recent.length - 1) / span : null];
};

/**
 * Camera capture, the WebSocket session, and the overlay for Live Detection. Strict flow
 * control: a frame is captured and sent only after the previous one was answered, never
 * faster than the target rate, and never while the page is hidden. All per-frame state is in a
 * ref and the overlay is drawn imperatively, so results do not re-render React.
 */
export function useLiveDetection(
  videoRef: RefObject<HTMLVideoElement | null>,
  canvasRef: RefObject<HTMLCanvasElement | null>,
  dependencies?: Partial<LiveDependencies>,
) {
  const deps = useRef<LiveDependencies>({ ...defaultDependencies(), ...dependencies });
  const run = useRef<Run | null>(null);
  const mirroredRef = useRef(true);
  const [phase, setPhase] = useState<LivePhase>("idle");
  const [connection, setConnection] = useState<LiveConnectionState>("idle");
  const [metrics, setMetrics] = useState<LiveMetrics>(EMPTY_METRICS);
  const [notice, setNotice] = useState<LiveNotice | null>(null);
  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [cameraId, setCameraId] = useState<string>("");
  const [mirrored, setMirroredState] = useState(true);
  /** Whether the server confirmed tracking for the running session, and where it runs. */
  const [tracking, setTracking] = useState(false);
  const [trackingMode, setTrackingMode] = useState<LiveTrackingMode | null>(null);

  const setMirrored = useCallback((value: boolean) => {
    mirroredRef.current = value;
    setMirroredState(value);
  }, []);

  const refreshCameras = useCallback(async () => {
    const media = deps.current.media();
    if (!media?.enumerateDevices) return;
    try {
      const found = await listCameras(media);
      setCameras(found);
      setCameraId((current) => (current && found.some((camera) => camera.deviceId === current)
        ? current : found[0]?.deviceId ?? ""));
    } catch {
      setCameras([]);
    }
  }, []);

  const snapshot = (current: Run): LiveMetrics => {
    const now = deps.current.now();
    const [results, fps] = rate(current.resultTimes, now);
    const [sends, submittedFps] = rate(current.sendTimes, now);
    current.resultTimes = results;
    current.sendTimes = sends;
    return {
      fps,
      submittedFps,
      roundTripMs: current.roundTripMs,
      trackingMs: current.trackingMs,
      device: current.device,
      precision: current.precision,
      latencyMs: current.latencyMs,
      inferenceMs: current.inferenceMs,
      processed: current.processed,
      dropped: current.dropped,
      detections: current.detections,
      activeTracks: current.activeTracks,
    };
  };

  /** Idempotent: stops capture, closes the socket, releases the camera, clears the overlay. */
  const finish = useCallback((next: LiveNotice | null) => {
    const current = run.current;
    if (!current || current.stopped) return;
    current.stopped = true;
    if (current.timer !== null) clearTimeout(current.timer);
    const socket = current.socket;
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      if (socket.readyState === WebSocket.OPEN) {
        try {
          socket.send(JSON.stringify({ type: "stop" }));
        } catch {
          // The socket is closing anyway.
        }
        socket.close(1000, "Client stop");
      } else if (socket.readyState === WebSocket.CONNECTING) {
        socket.close();
      }
    }
    stopStream(current.stream);
    current.tracker?.close(); // terminates the tracking Web Worker
    current.tracker = null;
    current.trails?.clear();
    current.trails = null;
    const video = videoRef.current;
    if (video) video.srcObject = null;
    clearOverlay(canvasRef.current);
    setMetrics(snapshot(current));
    run.current = null;
    setTracking(false);
    setTrackingMode(null);
    setPhase("idle");
    setConnection("idle");
    setNotice(next);
  }, [videoRef, canvasRef]);

  const schedule = (current: Run, delay?: number) => {
    if (current.stopped) return;
    if (current.timer !== null) clearTimeout(current.timer);
    const wait = delay ?? Math.max(0, current.intervalMs - (deps.current.now() - current.lastSentAt));
    current.timer = setTimeout(() => void pump(current), wait);
  };

  const pump = async (current: Run) => {
    current.timer = null;
    if (current.stopped || current.inFlight !== null || current.capturing) return;
    const socket = current.socket;
    const video = videoRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || !video) return;
    if (typeof document !== "undefined" && document.hidden) {
      schedule(current, 500); // paused while the tab is hidden
      return;
    }
    current.capturing = true;
    let frame: CapturedFrame | null = null;
    try {
      frame = await deps.current.captureFrame(video);
    } catch {
      frame = null;
    } finally {
      current.capturing = false;
    }
    if (current.stopped || current.inFlight !== null) return;
    if (!frame) {
      schedule(current, 100); // the video has no frame yet
      return;
    }
    current.frameId = current.frameId >= MAX_FRAME_ID ? 1 : current.frameId + 1;
    current.inFlight = current.frameId;
    current.sentAt = deps.current.now();
    current.lastSentAt = current.sentAt;
    current.sendTimes.push(current.sentAt);
    socket.send(encodeFrame(current.frameId, frame.buffer));
  };

  const handle = (current: Run, message: LiveServerMessage) => {
    switch (message.type) {
      case "ready":
        current.intervalMs = 1000 / Math.max(1, Math.min(LIVE_TARGET_FPS, message.maxFps));
        // Fresh state per session: track IDs of an earlier session or camera are never reused.
        current.trails = message.tracking ? new TrackTrails() : null;
        current.clientTracking = message.trackingMode === "CLIENT";
        if (current.clientTracking) {
          // One tracker per session in a Web Worker: IDs start at 1 and never leak between sessions.
          current.tracker = new LiveTrackerClient(message.sessionId, {
            ...DEFAULT_TRACKER_CONFIG,
            confidence: current.confidence,
            lowScoreFloor: Math.min(current.confidence, 0.1), // the worker's floor, also reported per frame
          }, deps.current.trackerWorker, (problem) => {
            current.tracker?.close();
            current.tracker = null;
            setNotice({ tone: "warning",
              text: `Tracking in the browser stopped (${problem}). Detections continue without Track IDs.` });
          });
        }
        setTracking(message.tracking);
        setTrackingMode(message.trackingMode);
        setPhase("running");
        setConnection("live");
        schedule(current, 0);
        break;
      case "detections": {
        if (message.frameId !== current.inFlight) return; // stale or out of order
        if (current.clientTracking) {
          receiveForClientTracking(current, message);
          return;
        }
        const now = deps.current.now();
        current.latencyMs = now - current.sentAt;
        current.inferenceMs = message.inferenceMs;
        current.processed += 1;
        current.roundTripMs = current.latencyMs;
        current.device = message.device;
        current.precision = message.precision;
        current.detections = message.detections.length;
        current.activeTracks = message.tracking ? message.activeTracks ?? 0 : null;
        if (message.tracking) current.trails?.update(message.detections);
        current.resultTimes.push(now);
        const canvas = canvasRef.current;
        const video = videoRef.current;
        if (canvas && video) {
          drawDetections(canvas, message, mirroredRef.current,
            { width: video.videoWidth || message.width, height: video.videoHeight || message.height },
            current.trails);
        }
        current.inFlight = null;
        schedule(current);
        break;
      }
      case "dropped":
        if (message.frameId === current.inFlight) current.inFlight = null;
        current.dropped += 1;
        schedule(current);
        break;
      case "error":
        if (message.fatal) {
          finish({ tone: "error", text: liveMessage(message.code, message.message) });
          return;
        }
        if (message.frameId === undefined || message.frameId === current.inFlight) current.inFlight = null;
        setNotice({ tone: "warning", text: liveMessage(message.code, message.message) });
        schedule(current);
        break;
      case "stopped":
        finish(message.reason === "CLIENT_STOP" ? null
          : { tone: "info", text: liveMessage(message.reason, "The live session ended.") });
        break;
    }
  };

  /** Draws one result on the overlay; never an older frame than the one already shown. */
  const render = (current: Run, result: LiveDetections) => {
    if (result.frameId <= current.lastDrawnFrameId) return;
    current.lastDrawnFrameId = result.frameId;
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (canvas && video) {
      drawDetections(canvas, result, mirroredRef.current,
        { width: video.videoWidth || result.width, height: video.videoHeight || result.height }, current.trails);
    }
  };

  /**
   * CLIENT tracking: the worker returned tracker input. The camera pipeline continues at once (the next
   * frame is not held back by tracking); the result is drawn when the browser's ByteTrack has run.
   */
  const receiveForClientTracking = (current: Run, message: LiveDetections) => {
    const sentAt = current.sentAt;
    current.roundTripMs = deps.current.now() - sentAt;
    current.inferenceMs = message.inferenceMs;
    current.device = message.device;
    current.precision = message.precision;
    current.processed += 1;
    current.inFlight = null;
    schedule(current);
    const finishDraw = (detections: LiveDetection[], activeTracks: number | null, tracking: boolean) => {
      if (current.stopped) return;
      const drawnAt = deps.current.now();
      current.latencyMs = drawnAt - sentAt;
      current.detections = detections.length;
      current.activeTracks = activeTracks;
      current.resultTimes.push(drawnAt);
      if (tracking) current.trails?.update(detections);
      render(current, { ...message, detections, tracking, activeTracks });
    };
    const tracker = current.tracker;
    if (!tracker) {
      // Tracking unavailable: show the detections at the confidence threshold, without IDs.
      finishDraw(message.detections.filter((d) => d.confidence >= current.confidence), null, false);
      return;
    }
    void tracker.track(message.frameId, sentAt, message.width, message.height, message.detections)
      .then((tracked) => {
        if (!tracked || current.stopped) return; // stale frame or session ended
        current.trackingMs = tracked.trackingMs;
        finishDraw(tracked.objects as LiveDetection[], tracked.activeTracks, true);
      });
  };

  const start = useCallback(async (settings: LiveSettings) => {
    if (run.current) return;
    const problem = cameraSupportProblem();
    if (problem) {
      setNotice({ tone: "error", text: problem.message });
      return;
    }
    const media = deps.current.media();
    if (!media) return;
    const current: Run = {
      stopped: false, socket: null, stream: null, frameId: 0, inFlight: null, sentAt: 0, lastSentAt: -Infinity,
      capturing: false, intervalMs: 1000 / LIVE_TARGET_FPS, timer: null, resultTimes: [], processed: 0,
      dropped: 0, latencyMs: null, inferenceMs: null, detections: 0, activeTracks: null, trails: null,
      tracker: null, clientTracking: false, confidence: settings.confidence, sendTimes: [], roundTripMs: null,
      trackingMs: null, device: null, precision: null, lastDrawnFrameId: 0,
    };
    run.current = current;
    setNotice(null);
    setMetrics(EMPTY_METRICS);
    setPhase("starting");
    let stream: MediaStream;
    try {
      stream = await openCamera(cameraId || undefined, media);
    } catch (error) {
      run.current = null;
      setPhase("idle");
      setNotice({ tone: "error", text: describeCameraError(error).message });
      return;
    }
    if (current.stopped) {
      stopStream(stream); // stopped while the permission prompt was open
      return;
    }
    current.stream = stream;
    stream.getVideoTracks().forEach((track) => track.addEventListener("ended", () =>
      finish({ tone: "warning", text: "The camera was disconnected." })));
    const video = videoRef.current;
    if (video) {
      video.srcObject = stream;
      await video.play().catch(() => undefined);
    }
    void refreshCameras();
    if (current.stopped) return;
    setConnection("connecting");
    let socket: WebSocket;
    try {
      socket = deps.current.createSocket(liveSocketUrl());
    } catch {
      finish({ tone: "error", text: "The live detection connection could not be opened." });
      return;
    }
    current.socket = socket;
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      const { trackingMode, ...rest } = settings;
      socket.send(JSON.stringify({
        type: "start", version: LIVE_PROTOCOL_VERSION, ...rest,
        ...(settings.tracking && trackingMode ? { trackingMode } : {}),
      }));
    };
    socket.onmessage = (event: MessageEvent) => {
      if (typeof event.data !== "string") return;
      const message = parseLiveMessage(event.data);
      if (message) handle(current, message);
    };
    socket.onclose = () => {
      finish({ tone: "error", text: "The connection to the live detection server was lost." });
    };
  }, [cameraId, finish, refreshCameras, videoRef]);

  const stop = useCallback(() => finish(null), [finish]);

  // Metrics are published at most twice a second, not once per frame.
  useEffect(() => {
    if (phase !== "running") return;
    const interval = setInterval(() => {
      if (run.current) setMetrics(snapshot(run.current));
    }, 500);
    return () => clearInterval(interval);
  }, [phase]);

  useEffect(() => {
    void refreshCameras();
    const media = deps.current.media();
    const onChange = () => void refreshCameras();
    media?.addEventListener?.("devicechange", onChange);
    return () => media?.removeEventListener?.("devicechange", onChange);
  }, [refreshCameras]);

  // Leaving the page (or unmounting) always releases the camera and the session.
  useEffect(() => () => finish(null), [finish]);

  return {
    phase, connection, metrics, notice, cameras, cameraId, setCameraId, mirrored, setMirrored, tracking,
    trackingMode, start, stop, dismissNotice: () => setNotice(null),
  };
}
