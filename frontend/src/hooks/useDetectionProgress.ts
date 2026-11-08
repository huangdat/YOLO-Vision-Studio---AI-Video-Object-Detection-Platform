import { useEffect, useState } from "react";
import { toApiError } from "../api/client";
import {
  detectionEventsUrl,
  getDetection,
  isJobId,
  parseProgressEvent,
} from "../api/detections";
import { isTerminal, JOB_STATUS, statusRank } from "../lib/jobStatus";
import type { DetectionProgressEvent } from "../types/detections";

export const PROGRESS_EVENTS = [
  "detection.progress",
  "detection.completed",
  "detection.failed",
  "detection.cancelled",
] as const;

export type ProgressConnection =
  | "idle"
  | "connecting"
  | "live"
  | "reconnecting"
  | "polling"
  | "closed";

export interface ProgressOptions {
  /** Connect only for non-terminal jobs; terminal jobs never change. */
  enabled: boolean;
  /** Fallback polling interval when SSE is unavailable. Conservative by default. */
  pollIntervalMs?: number;
  /** Consecutive SSE errors tolerated (native reconnect) before switching to polling. */
  maxStreamErrors?: number;
}

/**
 * True when `next` may replace `current`. Terminal snapshots are final; older snapshots
 * (by persisted timestamp) and backward stage moves are ignored, so a late or replayed
 * event can never overwrite newer state.
 */
export function isNewerSnapshot(
  next: DetectionProgressEvent,
  current: DetectionProgressEvent | null,
): boolean {
  if (!current) return true;
  if (isTerminal(current.status)) return false;
  const nextTime = Date.parse(next.timestamp);
  const currentTime = Date.parse(current.timestamp);
  if (!Number.isNaN(nextTime) && !Number.isNaN(currentTime) && nextTime < currentTime) {
    return false;
  }
  return statusRank(next.status) >= statusRank(current.status);
}

/**
 * Live job progress from GET /detections/{id}/events (Server-Sent Events), with a polling
 * fallback. The backend streams current-state snapshots, not a replayable history: after
 * a reconnect the first event is the latest persisted state. One EventSource per hook
 * instance; it is closed on terminal events, on unmount, and when the job id changes.
 */
export function useDetectionProgress(
  jobId: string | undefined,
  { enabled, pollIntervalMs = 5_000, maxStreamErrors = 3 }: ProgressOptions,
): { event: DetectionProgressEvent | null; connection: ProgressConnection } {
  const [event, setEvent] = useState<DetectionProgressEvent | null>(null);
  const [connection, setConnection] = useState<ProgressConnection>("idle");

  useEffect(() => {
    setEvent(null);
    if (!enabled || !isJobId(jobId)) {
      setConnection("idle");
      return;
    }
    let disposed = false;
    let source: EventSource | null = null;
    let pollTimer: number | undefined;
    let pollRequest: AbortController | null = null;
    let streamErrors = 0;

    const finish = (mode: ProgressConnection) => {
      disposed = true;
      source?.close();
      source = null;
      window.clearTimeout(pollTimer);
      pollRequest?.abort();
      setConnection(mode);
    };

    const apply = (next: DetectionProgressEvent) => {
      if (disposed || next.jobId.toLowerCase() !== jobId.toLowerCase()) return;
      setEvent((current) => (isNewerSnapshot(next, current) ? next : current));
      if (isTerminal(next.status)) finish("closed");
    };

    const poll = async () => {
      pollRequest = new AbortController();
      try {
        const job = await getDetection(jobId, pollRequest.signal);
        apply({
          jobId: job.jobId,
          status: job.status,
          progress: job.progress,
          message:
            job.status === "FAILED" && job.errorMessage
              ? job.errorMessage
              : JOB_STATUS[job.status].description,
          errorCode: job.errorCode,
          timestamp: job.updatedAt,
        });
      } catch (error: unknown) {
        const apiError = toApiError(error);
        if (apiError.kind === "cancelled") return;
        if (apiError.status === 404) {
          finish("closed");
          return;
        }
      }
      if (!disposed) pollTimer = window.setTimeout(() => void poll(), pollIntervalMs);
    };

    const startPolling = () => {
      source?.close();
      source = null;
      if (disposed) return;
      setConnection("polling");
      pollTimer = window.setTimeout(() => void poll(), pollIntervalMs);
    };

    if (typeof EventSource === "undefined") {
      startPolling();
    } else {
      setConnection("connecting");
      const stream = new EventSource(detectionEventsUrl(jobId));
      source = stream;
      const onMessage = (message: MessageEvent<string>) => {
        const parsed = parseProgressEvent(message.data);
        if (!parsed) return;
        streamErrors = 0;
        if (!disposed) setConnection("live");
        apply(parsed);
      };
      PROGRESS_EVENTS.forEach((name) =>
        stream.addEventListener(name, onMessage as EventListener),
      );
      stream.onopen = () => {
        streamErrors = 0;
        if (!disposed) setConnection("live");
      };
      stream.onerror = () => {
        if (disposed) return;
        streamErrors += 1;
        // CLOSED: the browser gave up (e.g. HTTP 404/503); otherwise it reconnects itself.
        if (stream.readyState === EventSource.CLOSED || streamErrors >= maxStreamErrors) {
          startPolling();
        } else {
          setConnection("reconnecting");
        }
      };
    }

    return () => {
      disposed = true;
      source?.close();
      window.clearTimeout(pollTimer);
      pollRequest?.abort();
    };
  }, [jobId, enabled, pollIntervalMs, maxStreamErrors]);

  return { event, connection };
}
