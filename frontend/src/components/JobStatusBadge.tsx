import { JOB_STATUS } from "../lib/jobStatus";
import type { DetectionJobStatus } from "../types/detections";

/** Detection job status: colour plus a text label, never colour alone. */
export function JobStatusBadge({ status }: { status: DetectionJobStatus }) {
  const meta = JOB_STATUS[status];
  return (
    <span className={`job-status tone-${meta.tone}`} title={meta.description}>
      <span className="job-status-dot" aria-hidden="true" />
      {meta.label}
    </span>
  );
}
