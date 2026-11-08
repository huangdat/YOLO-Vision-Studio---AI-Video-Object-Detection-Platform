import type { DetectionJobStatus } from "../types/detections";

export type StatusTone = "neutral" | "blue" | "purple" | "green" | "red" | "gray";

interface StatusMeta {
  label: string;
  tone: StatusTone;
  description: string;
}

/** Shared presentation of job statuses; labels are always shown, not only colours. */
export const JOB_STATUS: Record<DetectionJobStatus, StatusMeta> = {
  PENDING: { label: "Pending", tone: "neutral", description: "Accepted, waiting to be queued" },
  QUEUED: { label: "Queued", tone: "blue", description: "Waiting for a detection worker" },
  DOWNLOADING: { label: "Downloading", tone: "blue", description: "Downloading the video" },
  DETECTING: { label: "Detecting", tone: "purple", description: "Detecting objects in video frames" },
  ENCODING: { label: "Encoding", tone: "purple", description: "Encoding the annotated video" },
  UPLOADING: { label: "Uploading", tone: "purple", description: "Storing the results" },
  COMPLETED: { label: "Completed", tone: "green", description: "Detection completed" },
  FAILED: { label: "Failed", tone: "red", description: "Detection failed" },
  CANCELLED: { label: "Cancelled", tone: "gray", description: "Detection job cancelled" },
};

const TERMINAL: ReadonlySet<DetectionJobStatus> = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

export function isTerminal(status: DetectionJobStatus): boolean {
  return TERMINAL.has(status);
}

/** Order of the forward-only lifecycle; terminal states rank highest. */
const ORDER: Record<DetectionJobStatus, number> = {
  PENDING: 0,
  QUEUED: 1,
  DOWNLOADING: 2,
  DETECTING: 3,
  ENCODING: 4,
  UPLOADING: 5,
  COMPLETED: 6,
  FAILED: 6,
  CANCELLED: 6,
};

export function statusRank(status: DetectionJobStatus): number {
  return ORDER[status];
}
