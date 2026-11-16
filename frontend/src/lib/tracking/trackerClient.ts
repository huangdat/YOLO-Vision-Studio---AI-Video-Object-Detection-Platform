import type { TrackerConfig, TrackerDetection } from "./byteTracker";
import { TrackerHost } from "./trackerHost";
import type { TrackerRequest, TrackerResponse } from "./trackerProtocol";

export type TrackedFrame = Extract<TrackerResponse, { type: "TRACKED" }>;

/** Minimal Worker surface, so tests can substitute an in-process implementation. */
export interface WorkerLike {
  postMessage(message: TrackerRequest): void;
  terminate(): void;
  onmessage: ((event: MessageEvent<TrackerResponse>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
}

/**
 * The same TrackerHost on the main thread, asynchronously. Used only where module Web Workers are
 * unavailable (old browsers, tests); results are identical, only the thread differs.
 */
export class InProcessTrackerWorker implements WorkerLike {
  onmessage: ((event: MessageEvent<TrackerResponse>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  private readonly host = new TrackerHost();
  private terminated = false;

  postMessage(message: TrackerRequest): void {
    queueMicrotask(() => {
      if (this.terminated) return;
      for (const response of this.host.handle(message)) {
        this.onmessage?.({ data: response } as MessageEvent<TrackerResponse>);
      }
    });
  }

  terminate(): void {
    this.terminated = true;
  }
}

export function createTrackerWorker(): WorkerLike {
  if (typeof Worker === "undefined") return new InProcessTrackerWorker();
  try {
    return new Worker(new URL("../../workers/tracker.worker.ts", import.meta.url), { type: "module" }) as WorkerLike;
  } catch {
    return new InProcessTrackerWorker();
  }
}

/**
 * Page-side handle of the tracking Web Worker for one live session. Frames are answered in the order
 * they were sent (the worker is single-threaded); a skipped (stale) frame resolves to null.
 */
export class LiveTrackerClient {
  private readonly worker: WorkerLike;
  private readonly pending = new Map<number, (frame: TrackedFrame | null) => void>();
  private closed = false;

  constructor(readonly sessionId: string, config: TrackerConfig, factory: () => WorkerLike = createTrackerWorker,
              private readonly onError: (message: string) => void = () => undefined) {
    this.worker = factory();
    this.worker.onmessage = (event) => this.receive(event.data);
    this.worker.onerror = (event) => {
      this.onError(event.message || "The tracking worker failed.");
      this.flush();
    };
    this.worker.postMessage({ type: "INIT", sessionId, config });
  }

  track(frameId: number, timestampMs: number, width: number, height: number,
        detections: TrackerDetection[]): Promise<TrackedFrame | null> {
    if (this.closed) return Promise.resolve(null);
    return new Promise((resolve) => {
      this.pending.set(frameId, resolve);
      this.worker.postMessage({ type: "TRACK_FRAME", sessionId: this.sessionId, frameId, timestampMs, width, height,
        detections });
    });
  }

  reset(): void {
    if (!this.closed) this.worker.postMessage({ type: "RESET", sessionId: this.sessionId });
  }

  /** Releases the session and terminates the worker; pending frames resolve to null. */
  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.worker.postMessage({ type: "CLOSE", sessionId: this.sessionId });
    this.worker.terminate();
    this.flush();
  }

  private receive(response: TrackerResponse): void {
    if (response.sessionId !== this.sessionId) return;
    if (response.type === "TRACKED" || response.type === "SKIPPED") {
      const resolve = this.pending.get(response.frameId);
      this.pending.delete(response.frameId);
      resolve?.(response.type === "TRACKED" ? response : null);
    } else if (response.type === "ERROR") {
      this.onError(response.message);
    }
  }

  private flush(): void {
    for (const resolve of this.pending.values()) resolve(null);
    this.pending.clear();
  }
}
