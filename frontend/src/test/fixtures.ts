import type { PageResponse } from "../types/api";
import type {
  DetectionJob,
  DetectionJobStatus,
  DetectionJobSummary,
  DetectionProgressEvent,
  DetectionResultMetadata,
} from "../types/detections";
import type { ModelConfig } from "../types/models";

export const JOB_ID = "596b71b1-ea62-4d75-8f34-679e3bd0b5c9";

export function model(overrides: Partial<ModelConfig> = {}): ModelConfig {
  const key = overrides.modelKey ?? "yolo11n";
  return {
    id: `id-${key}`,
    modelKey: key,
    version: "YOLO11",
    modelSize: "n",
    taskType: "DETECT",
    weightsFilename: `${key}.pt`,
    enabled: false,
    createdAt: "2026-11-08T09:00:00Z",
    updatedAt: "2026-11-08T09:00:00Z",
    ...overrides,
  };
}

export function summary(overrides: Partial<DetectionJobSummary> = {}): DetectionJobSummary {
  return {
    jobId: JOB_ID,
    modelKey: "yolo11n",
    status: "COMPLETED",
    progress: 100,
    createdAt: "2026-11-08T11:13:21Z",
    completedAt: "2026-11-08T11:13:38Z",
    errorCode: null,
    ...overrides,
  };
}

export function page<T>(content: T[], overrides: Partial<PageResponse<T>> = {}): PageResponse<T> {
  return {
    content,
    page: 0,
    size: 10,
    totalElements: content.length,
    totalPages: content.length === 0 ? 0 : 1,
    ...overrides,
  };
}

export function job(overrides: Partial<DetectionJob> = {}): DetectionJob {
  return {
    jobId: JOB_ID,
    modelKey: "yolo11n",
    modelVersion: "YOLO11",
    sourceType: "YOUTUBE_URL",
    videoUrl: "https://www.youtube.com/watch?v=abcdefghijk",
    status: "DETECTING",
    progress: 40,
    confidence: 0.25,
    imageSize: 320,
    classes: [1, 2, 3, 5, 7],
    createdAt: "2026-11-08T11:13:21Z",
    startedAt: "2026-11-08T11:13:28Z",
    completedAt: null,
    updatedAt: "2026-11-08T11:13:30Z",
    errorCode: null,
    errorMessage: null,
    ...overrides,
  };
}

export function result(overrides: Partial<DetectionResultMetadata> = {}): DetectionResultMetadata {
  return {
    jobId: JOB_ID,
    status: "COMPLETED",
    modelKey: "yolo11n",
    modelVersion: "YOLO11",
    totalFrames: 60,
    totalDetections: 72,
    processingTimeMs: 10317,
    detectionSummary: { bus: 60, car: 12 },
    countSemantics: "BOUNDING_BOX_DETECTIONS_ACROSS_FRAMES",
    outputVideoAvailable: true,
    resultMetadataAvailable: true,
    createdAt: "2026-11-08T11:13:38Z",
    completedAt: "2026-11-08T11:13:38Z",
    ...overrides,
  };
}

export function progressEvent(
  status: DetectionJobStatus,
  progress: number,
  timestamp: string,
  overrides: Partial<DetectionProgressEvent> = {},
): DetectionProgressEvent {
  return {
    jobId: JOB_ID,
    status,
    progress,
    message: null,
    errorCode: null,
    timestamp,
    ...overrides,
  };
}

type Listener = (event: { data: string }) => void;

/** Controllable stand-in for the browser EventSource (jsdom has none). */
export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readonly url: string;
  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private readonly listeners = new Map<string, Set<Listener>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }

  removeEventListener(type: string, listener: Listener) {
    this.listeners.get(type)?.delete(listener);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }

  get closed() {
    return this.readyState === FakeEventSource.CLOSED;
  }

  open() {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }

  emit(type: string, payload: unknown) {
    const data = typeof payload === "string" ? payload : JSON.stringify(payload);
    this.listeners.get(type)?.forEach((listener) => listener({ data }));
  }

  /** Simulates a dropped connection; `permanent` mimics the browser giving up (HTTP error). */
  fail(permanent = false) {
    this.readyState = permanent ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING;
    this.onerror?.();
  }

  static open(): FakeEventSource[] {
    return FakeEventSource.instances.filter((instance) => !instance.closed);
  }

  static reset() {
    FakeEventSource.instances = [];
  }
}
