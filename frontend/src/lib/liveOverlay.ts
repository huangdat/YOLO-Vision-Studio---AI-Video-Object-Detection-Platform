import { classLabel } from "./format";
import type { LiveDetections } from "./liveProtocol";

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

/** Draws one result on the overlay canvas (sized to its CSS box at device pixel ratio). */
export function drawDetections(canvas: HTMLCanvasElement, result: LiveDetections, mirrored: boolean,
  media: { width: number; height: number }): void {
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
  context.lineWidth = 2;
  context.font = "600 13px system-ui, sans-serif";
  context.textBaseline = "top";
  for (const detection of result.detections) {
    const rect = mapBox(detection.box, result.width, result.height, content, mirrored);
    const color = COLORS[detection.classId % COLORS.length];
    context.strokeStyle = color;
    context.strokeRect(rect.x, rect.y, rect.width, rect.height);
    const label = `${classLabel(detection.label)} ${Math.round(detection.confidence * 100)}%`;
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
