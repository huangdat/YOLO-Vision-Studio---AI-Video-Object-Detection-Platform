import { ByteTracker, type TrackerConfig } from "./byteTracker";
import type { TrackerRequest, TrackerResponse } from "./trackerProtocol";

/** A pause longer than this restarts a session's tracker (the server's live session TTL is 30 s). */
export const DEFAULT_MAX_GAP_MS = 30_000;
/** One browser tab normally tracks one live session; a few are allowed for reconnects. */
export const MAX_SESSIONS = 4;

interface Session {
  config: TrackerConfig;
  tracker: ByteTracker | null;
  lastFrameId: number;
  lastTimestampMs: number;
}

/**
 * Tracking state of the Web Worker, kept per live session and never shared between sessions.
 * Frames must arrive in increasing frameId order: an older or repeated frame is skipped (STALE) so
 * ByteTrack never sees time go backwards. Frames the server dropped simply never arrive; each processed
 * frame is one tracker step, exactly like the server-side live tracker.
 */
export class TrackerHost {
  private readonly sessions = new Map<string, Session>();

  constructor(private readonly now: () => number = () => performance.now(),
              private readonly maxGapMs = DEFAULT_MAX_GAP_MS) {}

  get sessionCount(): number {
    return this.sessions.size;
  }

  handle(request: TrackerRequest): TrackerResponse[] {
    switch (request.type) {
      case "INIT": {
        if (!this.sessions.has(request.sessionId) && this.sessions.size >= MAX_SESSIONS) {
          // Bounded memory: the oldest session gives way (a closed tab that never sent CLOSE).
          const oldest = this.sessions.keys().next().value as string;
          this.sessions.delete(oldest);
        }
        try {
          new ByteTracker(request.config); // validate the configuration eagerly
        } catch (error) {
          return [{ type: "ERROR", sessionId: request.sessionId, message: (error as Error).message }];
        }
        this.sessions.set(request.sessionId, {
          config: request.config, tracker: null, lastFrameId: -1, lastTimestampMs: Number.NEGATIVE_INFINITY,
        });
        return [{ type: "READY", sessionId: request.sessionId }];
      }
      case "TRACK_FRAME": {
        const session = this.sessions.get(request.sessionId);
        if (!session) return [{ type: "SKIPPED", sessionId: request.sessionId, frameId: request.frameId, reason: "UNKNOWN_SESSION" }];
        if (request.frameId <= session.lastFrameId) {
          return [{ type: "SKIPPED", sessionId: request.sessionId, frameId: request.frameId, reason: "STALE" }];
        }
        const restarted = session.tracker === null || request.timestampMs - session.lastTimestampMs > this.maxGapMs;
        if (restarted) session.tracker = new ByteTracker(session.config);
        const started = this.now();
        const result = session.tracker!.update(request.detections);
        const trackingMs = this.now() - started;
        session.lastFrameId = request.frameId;
        session.lastTimestampMs = request.timestampMs;
        return [{
          type: "TRACKED", sessionId: request.sessionId, frameId: request.frameId, timestampMs: request.timestampMs,
          width: request.width, height: request.height, objects: result.objects, activeTracks: result.activeTracks,
          trackingMs, restarted,
        }];
      }
      case "RESET": {
        const session = this.sessions.get(request.sessionId);
        if (session) {
          session.tracker = null;
          session.lastFrameId = -1;
          session.lastTimestampMs = Number.NEGATIVE_INFINITY;
        }
        return [];
      }
      case "CLOSE":
        this.sessions.delete(request.sessionId);
        return [{ type: "CLOSED", sessionId: request.sessionId }];
    }
  }
}
