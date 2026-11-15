import { classLabel } from "./format";
import type { LiveDetection, LiveDetections } from "./liveProtocol";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Where a video with `object-fit: contain` is drawn inside its element (letterboxing). */
export function containRect(boxWidth: number, boxHeight: number, mediaWidth: number, mediaHeight: number): Rect {
  if (boxWidth <= 0 || boxHeight <= 0 || mediaWidth <= 0 || mediaHeight <= 0) {
    return { x: 0, y: 0, width: 0, height: 0 };
  }
  const scale = Math.min(boxWidth / mediaWidth, boxHeight / mediaHeight);
  const width = mediaWidth * scale;
  const height = mediaHeight * scale;
  return { x: (boxWidth - width) / 2, y: (boxHeight - height) / 2, width, height };
}

/**
 * Maps a box in submitted-frame pixels to overlay CSS pixels. `content` is where the video is
 * displayed; mirroring flips x because the preview (not the submitted frame) is mirrored.
 */
export function mapBox(box: [number, number, number, number], frameWidth: number, frameHeight: number,
  content: Rect, mirrored: boolean): Rect {
  const sx = content.width / frameWidth;
  const sy = content.height / frameHeight;
  const left = mirrored ? frameWidth - box[2] : box[0];
  const right = mirrored ? frameWidth - box[0] : box[2];
  return {
    x: content.x + left * sx,
    y: content.y + box[1] * sy,
    width: (right - left) * sx,
    height: (box[3] - box[1]) * sy,
  };
}

const COLORS = ["#2563eb", "#16a34a", "#d97706", "#db2777", "#7c3aed", "#0891b2", "#dc2626", "#4d7c0f"];
const UNTRACKED_COLOR = "#64748b";

/** 'Person #3 · 91%' for a confirmed track, 'Person 91%' otherwise (IDs come only from the server). */
export function detectionLabel(detection: LiveDetection): string {
  const percent = `${Math.round(detection.confidence * 100)}%`;
  return detection.trackId === null
    ? `${classLabel(detection.label)} ${percent}`
    : `${classLabel(detection.label)} #${detection.trackId} · ${percent}`;
}

/**
 * Short, bounded trails of the worker's track IDs (frame-pixel centers). Memory is capped by
 * the point count per track, the number of tracks, and how long an unseen track is kept.
 */
export class TrackTrails {
  private readonly points = new Map<number, [number, number][]>();
  private readonly lastSeen = new Map<number, number>();
  private frame = 0;

  constructor(readonly length = 12, readonly maxAge = 10, readonly maxTracks = 64) {}

  update(detections: LiveDetection[]): void {
    this.frame += 1;
    for (const detection of detections) {
      if (detection.trackId === null) continue;
      const [x1, y1, x2, y2] = detection.box;
      const trail = this.points.get(detection.trackId) ?? [];
      trail.push([(x1 + x2) / 2, (y1 + y2) / 2]);
      if (trail.length > this.length) trail.splice(0, trail.length - this.length);
      this.points.delete(detection.trackId); // re-insert: Map order is least recently seen first
      this.points.set(detection.trackId, trail);
      this.lastSeen.set(detection.trackId, this.frame);
    }
    for (const [id, seen] of this.lastSeen) {
      if (this.frame - seen > this.maxAge) this.forget(id);
    }
    while (this.points.size > this.maxTracks) this.forget(this.points.keys().next().value as number);
  }

  trail(trackId: number): [number, number][] {
    return this.points.get(trackId) ?? [];
  }

  get size(): number {
    return this.points.size;
  }

  clear(): void {
    this.points.clear();
    this.lastSeen.clear();
    this.frame = 0;
  }

  private forget(id: number): void {
    this.points.delete(id);
    this.lastSeen.delete(id);
  }
}

function colorFor(detection: LiveDetection, tracking: boolean): string {
  if (!tracking) return COLORS[detection.classId % COLORS.length];
  return detection.trackId === null ? UNTRACKED_COLOR : COLORS[detection.trackId % COLORS.length];
}

/** Draws one result on the overlay canvas (sized to its CSS box at device pixel ratio). */
export function drawDetections(canvas: HTMLCanvasElement, result: LiveDetections, mirrored: boolean,
  media: { width: number; height: number }, trails?: TrackTrails | null): void {
  const context = canvas.getContext("2d");
  if (!context) return;
  const ratio = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight;
  if (canvas.width !== Math.round(cssWidth * ratio) || canvas.height !== Math.round(cssHeight * ratio)) {
    canvas.width = Math.round(cssWidth * ratio);
    canvas.height = Math.round(cssHeight * ratio);
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, cssWidth, cssHeight);
  const content = containRect(cssWidth, cssHeight, media.width, media.height);
  if (trails && result.tracking) {
    context.lineWidth = 2;
    context.globalAlpha = 0.55;
    for (const detection of result.detections) {
      if (detection.trackId === null) continue;
      const points = trails.trail(detection.trackId);
      if (points.length < 2) continue;
      context.strokeStyle = colorFor(detection, true);
      context.beginPath();
      points.forEach(([x, y], index) => {
        const point = mapBox([x, y, x, y], result.width, result.height, content, mirrored);
        if (index === 0) context.moveTo(point.x, point.y);
        else context.lineTo(point.x, point.y);
      });
      context.stroke();
    }
    context.globalAlpha = 1;
  }
  context.lineWidth = 2;
  context.font = "600 13px system-ui, sans-serif";
  context.textBaseline = "top";
  for (const detection of result.detections) {
    const rect = mapBox(detection.box, result.width, result.height, content, mirrored);
    const color = colorFor(detection, result.tracking);
    context.strokeStyle = color;
    context.strokeRect(rect.x, rect.y, rect.width, rect.height);
    const label = detectionLabel(detection);
    const textWidth = context.measureText(label).width + 10;
    const labelY = rect.y >= 20 ? rect.y - 20 : rect.y;
    context.fillStyle = color;
    context.fillRect(rect.x, labelY, textWidth, 20);
    context.fillStyle = "#ffffff";
    context.fillText(label, rect.x + 5, labelY + 3);
  }
}

export function clearOverlay(canvas: HTMLCanvasElement | null): void {
  const context = canvas?.getContext("2d");
  if (canvas && context) {
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.clearRect(0, 0, canvas.width, canvas.height);
  }
}
