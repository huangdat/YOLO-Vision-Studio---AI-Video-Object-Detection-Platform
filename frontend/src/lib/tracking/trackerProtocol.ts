import type { TrackedDetection, TrackerConfig, TrackerDetection } from "./byteTracker";

/** Messages from the page to the tracking Web Worker. */
export type TrackerRequest =
  | { type: "INIT"; sessionId: string; config: TrackerConfig }
  | {
      type: "TRACK_FRAME";
      sessionId: string;
      /** Live frame id; must increase within a session. */
      frameId: number;
      /** Capture time of the frame (performance.now() ms). */
      timestampMs: number;
      width: number;
      height: number;
      detections: TrackerDetection[];
    }
  | { type: "RESET"; sessionId: string }
  | { type: "CLOSE"; sessionId: string };

/** Messages from the tracking Web Worker to the page. */
export type TrackerResponse =
  | { type: "READY"; sessionId: string }
  | {
      type: "TRACKED";
      sessionId: string;
      frameId: number;
      timestampMs: number;
      width: number;
      height: number;
      objects: TrackedDetection[];
      activeTracks: number;
      /** Time ByteTrack took for this frame inside the worker. */
      trackingMs: number;
      /** True when this frame started a new tracker (first frame, or after a long pause). */
      restarted: boolean;
    }
  | { type: "SKIPPED"; sessionId: string; frameId: number; reason: "STALE" | "UNKNOWN_SESSION" }
  | { type: "CLOSED"; sessionId: string }
  | { type: "ERROR"; sessionId: string; message: string };
