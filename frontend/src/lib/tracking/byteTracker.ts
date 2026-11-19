/**
 * ByteTrack for one ordered stream of frames, ported from Ultralytics' BYTETracker (the tracker the
 * Python workers use, ultralytics 8.4.207) so the browser and the server associate detections the
 * same way:
 *
 * - Two association stages: high-score boxes (>= trackHighThresh) are matched to all tracked and lost
 *   tracks with score-fused IoU (threshold matchThresh), then low-score boxes (lowScoreFloor < score <
 *   trackHighThresh) to the still-unmatched tracked tracks with plain IoU (threshold 0.5).
 * - Kalman prediction (constant velocity in x, y, aspect, height) before matching.
 * - New tracks start from unmatched high-score boxes (>= newTrackThresh) and are confirmed by a match in
 *   the next frame (immediately in the first frame); unconfirmed tracks that miss a frame are removed.
 * - Lost tracks are kept for trackBuffer frames and can be re-found with the same ID.
 * - Duplicates between tracked and lost tracks (IoU > 0.85) are resolved in favour of the older track.
 *
 * Numerics follow the reference: boxes, scores and IoUs are rounded to float32 where NumPy works in
 * float32, the Kalman filter runs in float64. IDs start at 1 per tracker instance (per live session).
 */

import { kalmanFilter, type KalmanState } from "./kalmanFilter";
import { linearAssignment } from "./linearAssignment";

const f32 = Math.fround;

export interface TrackerConfig {
  /** User confidence: first-stage threshold, new-track threshold, and reporting threshold. */
  confidence: number;
  /** YOLO ran at this score; second-stage boxes are above it. min(confidence, 0.1) like the server. */
  lowScoreFloor: number;
  /** Frames a lost track is kept before its ID is retired. */
  trackBuffer: number;
  matchThresh: number;
  fuseScore: boolean;
}

export const DEFAULT_TRACKER_CONFIG: Omit<TrackerConfig, "confidence" | "lowScoreFloor"> = {
  trackBuffer: 10, // LIVE_TRACKING_TRACK_BUFFER: live frames are sparse
  matchThresh: 0.8,
  fuseScore: true,
};

/** One detection of a frame, in pixels of that frame. */
export interface TrackerDetection {
  classId: number;
  confidence: number;
  /** [x1, y1, x2, y2] */
  box: [number, number, number, number];
}

export interface TrackedDetection extends TrackerDetection {
  /** Confirmed Track ID, or null for a detection without a confirmed track. */
  trackId: number | null;
}

export interface TrackerFrameResult {
  /** Detections at or above the confidence plus lower-score boxes that continued a track, in input order. */
  objects: TrackedDetection[];
  activeTracks: number;
}

enum State {
  New,
  Tracked,
  Lost,
  Removed,
}

class STrack {
  trackId = 0;
  isActivated = false;
  state = State.New;
  startFrame = 0;
  frameId = 0;
  trackletLen = 0;
  kalman: KalmanState | null = null;
  /** float32 top-left x, y, width, height of the detection. */
  readonly detTlwh: [number, number, number, number];

  constructor(xywh: [number, number, number, number], public score: number, public cls: number,
              public idx: number) {
    const [cx, cy, w, h] = xywh;
    this.detTlwh = [f32(cx - w / 2), f32(cy - h / 2), w, h];
  }

  get endFrame(): number {
    return this.frameId;
  }

  /** Current box: the Kalman estimate when initialised (float64), else the detection. */
  tlwh(): [number, number, number, number] {
    if (!this.kalman) return [...this.detTlwh];
    const [x, y, a, h] = this.kalman.mean;
    const w = a * h;
    return [x - w / 2, y - h / 2, w, h];
  }

  xyxy(): [number, number, number, number] {
    const [x, y, w, h] = this.tlwh();
    return [x, y, x + w, y + h];
  }

  /** Detection box as (x, y, a, h), computed in float32 like the reference. */
  measurement(): number[] {
    const [l, t, w, h] = this.detTlwh;
    return [f32(l + f32(w / 2)), f32(t + f32(h / 2)), f32(w / h), h];
  }

  activate(frameId: number, nextId: () => number) {
    this.trackId = nextId();
    this.kalman = kalmanFilter.initiate(this.measurement());
    this.trackletLen = 0;
    this.state = State.Tracked;
    if (frameId === 1) this.isActivated = true;
    this.frameId = frameId;
    this.startFrame = frameId;
  }

  reActivate(detection: STrack, frameId: number) {
    this.kalman = kalmanFilter.update(this.kalman!, detection.measurement());
    this.trackletLen = 0;
    this.state = State.Tracked;
    this.isActivated = true;
    this.frameId = frameId;
    this.score = detection.score;
    this.cls = detection.cls;
    this.idx = detection.idx;
  }

  update(detection: STrack, frameId: number) {
    this.frameId = frameId;
    this.trackletLen += 1;
    this.kalman = kalmanFilter.update(this.kalman!, detection.measurement());
    this.state = State.Tracked;
    this.isActivated = true;
    this.score = detection.score;
    this.cls = detection.cls;
    this.idx = detection.idx;
  }
}

/** IoU matrix in float32 arithmetic (Ultralytics bbox_ioa with iou=True, eps 1e-7). */
function iouMatrix(a: [number, number, number, number][], b: [number, number, number, number][]): number[][] {
  const eps = f32(1e-7);
  const boxesA = a.map((box) => box.map(f32));
  const boxesB = b.map((box) => box.map(f32));
  return boxesA.map(([ax1, ay1, ax2, ay2]) => {
    const areaA = f32(f32(ax2 - ax1) * f32(ay2 - ay1));
    return boxesB.map(([bx1, by1, bx2, by2]) => {
      const iw = Math.max(0, f32(Math.min(ax2, bx2) - Math.max(ax1, bx1)));
      const ih = Math.max(0, f32(Math.min(ay2, by2) - Math.max(ay1, by1)));
      const inter = f32(iw * ih);
      const areaB = f32(f32(bx2 - bx1) * f32(by2 - by1));
      const union = f32(f32(areaB + areaA) - inter);
      return f32(inter / f32(union + eps));
    });
  });
}

function iouDistance(tracks: STrack[], detections: STrack[]): number[][] {
  if (!tracks.length || !detections.length) return tracks.map(() => []);
  return iouMatrix(tracks.map((t) => t.xyxy()), detections.map((d) => d.xyxy()))
    .map((row) => row.map((iou) => f32(1 - iou)));
}

function fuseScore(cost: number[][], detections: STrack[]): number[][] {
  return cost.map((row) => row.map((value, j) => f32(1 - f32(f32(1 - value) * detections[j].score))));
}

function joint(a: STrack[], b: STrack[]): STrack[] {
  const ids = new Set(a.map((t) => t.trackId));
  return [...a, ...b.filter((t) => !ids.has(t.trackId))];
}

function subtract(a: STrack[], b: STrack[]): STrack[] {
  const ids = new Set(b.map((t) => t.trackId));
  return a.filter((t) => !ids.has(t.trackId));
}

function removeDuplicates(a: STrack[], b: STrack[]): [STrack[], STrack[]] {
  const distance = iouDistance(a, b);
  const dropA = new Set<number>();
  const dropB = new Set<number>();
  distance.forEach((row, p) => row.forEach((value, q) => {
    if (value < 0.15) {
      const timeP = a[p].frameId - a[p].startFrame;
      const timeQ = b[q].frameId - b[q].startFrame;
      if (timeP > timeQ) dropB.add(q);
      else dropA.add(p);
    }
  }));
  return [a.filter((_, i) => !dropA.has(i)), b.filter((_, i) => !dropB.has(i))];
}

const REMOVED_BUFFER = 1000;

export class ByteTracker {
  private tracked: STrack[] = [];
  private lost: STrack[] = [];
  private removed: STrack[] = [];
  private frameId = 0;
  private lastId = 0;
  private readonly high: number;
  private readonly low: number;
  private readonly newTrack: number;

  constructor(readonly config: TrackerConfig) {
    if (!(config.confidence >= 0 && config.confidence <= 1)) throw new Error("confidence must be between 0 and 1");
    if (!(config.trackBuffer >= 1)) throw new Error("trackBuffer must be positive");
    this.high = f32(config.confidence);
    this.low = f32(config.lowScoreFloor);
    this.newTrack = f32(config.confidence);
  }

  /** Number of processed frames. */
  get frames(): number {
    return this.frameId;
  }

  private readonly nextId = () => ++this.lastId;

  /** Associates one frame. Frames must arrive in order; an empty list still ages lost tracks. */
  update(input: TrackerDetection[]): TrackerFrameResult {
    this.frameId += 1;
    const frame = this.frameId;
    const activated: STrack[] = [];
    const refind: STrack[] = [];
    const lostNow: STrack[] = [];
    const removedNow: STrack[] = [];

    const high: STrack[] = [];
    const low: STrack[] = [];
    input.forEach((detection, index) => {
      const [x1, y1, x2, y2] = detection.box.map(f32);
      const w = f32(x2 - x1);
      const h = f32(y2 - y1);
      const score = f32(detection.confidence);
      if (!(w > 0 && h > 0)) return; // the Kalman state divides by height
      const xywh: [number, number, number, number] = [f32(f32(x1 + x2) / 2), f32(f32(y1 + y2) / 2), w, h];
      if (score >= this.high) high.push(new STrack(xywh, score, detection.classId, index));
      else if (score > this.low) low.push(new STrack(xywh, score, detection.classId, index));
    });

    const unconfirmed = this.tracked.filter((t) => !t.isActivated);
    const confirmed = this.tracked.filter((t) => t.isActivated);
    const pool = joint(confirmed, this.lost);
    for (const track of pool) {
      const mean = [...track.kalman!.mean];
      if (track.state !== State.Tracked) mean[7] = 0;
      track.kalman = kalmanFilter.predict({ mean, covariance: track.kalman!.covariance });
    }

    // First association: high-score boxes with all tracked and lost tracks.
    const apply = (track: STrack, detection: STrack) => {
      if (track.state === State.Tracked) {
        track.update(detection, frame);
        activated.push(track);
      } else {
        track.reActivate(detection, frame);
        refind.push(track);
      }
    };
    const first = linearAssignment(this.distances(pool, high), this.config.matchThresh, high.length);
    first.matches.forEach(([t, d]) => apply(pool[t], high[d]));

    // Second association: low-score boxes with the remaining tracked tracks.
    const remaining = first.unmatchedRows.map((i) => pool[i]).filter((t) => t.state === State.Tracked);
    let stillUnmatched = remaining.map((_, i) => i);
    if (remaining.length && low.length) {
      const second = linearAssignment(iouDistance(remaining, low), 0.5, low.length);
      second.matches.forEach(([t, d]) => apply(remaining[t], low[d]));
      stillUnmatched = second.unmatchedRows;
    }
    for (const index of stillUnmatched) {
      remaining[index].state = State.Lost;
      lostNow.push(remaining[index]);
    }

    // Unconfirmed tracks (one frame old) with the leftover high-score boxes.
    const leftover = first.unmatchedColumns.map((i) => high[i]);
    let newCandidates = leftover.map((_, i) => i);
    if (unconfirmed.length) {
      const third = linearAssignment(this.distances(unconfirmed, leftover), 0.7, leftover.length);
      third.matches.forEach(([t, d]) => {
        unconfirmed[t].update(leftover[d], frame);
        activated.push(unconfirmed[t]);
      });
      for (const index of third.unmatchedRows) {
        unconfirmed[index].state = State.Removed;
        removedNow.push(unconfirmed[index]);
      }
      newCandidates = third.unmatchedColumns;
    }

    for (const index of newCandidates) {
      const track = leftover[index];
      if (track.score < this.newTrack) continue;
      track.activate(frame, this.nextId);
      activated.push(track);
    }

    for (const track of this.lost) {
      if (frame - track.endFrame > this.config.trackBuffer) {
        track.state = State.Removed;
        removedNow.push(track);
      }
    }

    this.tracked = this.tracked.filter((t) => t.state === State.Tracked);
    this.tracked = joint(this.tracked, activated);
    this.tracked = joint(this.tracked, refind);
    this.lost = subtract(this.lost, this.tracked);
    this.lost.push(...lostNow);
    this.lost = subtract(this.lost, this.removed);
    [this.tracked, this.lost] = removeDuplicates(this.tracked, this.lost);
    this.removed.push(...removedNow);
    if (this.removed.length > REMOVED_BUFFER) this.removed = this.removed.slice(-REMOVED_BUFFER);

    // Report like the Python ObjectTracker: input order, the detection's own box, confirmed IDs only.
    const ids = new Map<number, number>();
    for (const track of this.tracked) if (track.isActivated) ids.set(track.idx, track.trackId);
    const objects: TrackedDetection[] = [];
    input.forEach((detection, index) => {
      const trackId = ids.get(index) ?? null;
      // Reporting compares Python floats (float64) in ObjectTracker; only the tracker itself uses float32.
      if (trackId !== null || detection.confidence >= this.config.confidence) objects.push({ ...detection, trackId });
    });
    return { objects, activeTracks: ids.size };
  }

  private distances(tracks: STrack[], detections: STrack[]): number[][] {
    const distance = iouDistance(tracks, detections);
    return this.config.fuseScore ? fuseScore(distance, detections) : distance;
  }

  /** Number of tracks held in memory (tracked + lost); removed tracks are not referenced. */
  get size(): number {
    return this.tracked.length + this.lost.length;
  }
}
