import { Link } from "react-router-dom";
import { formatDateTime, shortId } from "../lib/format";
import { JOB_STATUS } from "../lib/jobStatus";
import type { DetectionJobSummary } from "../types/detections";
import { Icon } from "./Icon";
import { JobStatusBadge } from "./JobStatusBadge";
import { ProgressBar } from "./ProgressBar";

/** Job rows (history and recent activity). Scrolls horizontally on narrow screens. */
export function DetectionTable({
  jobs,
  caption,
  showCompleted = true,
}: {
  jobs: DetectionJobSummary[];
  caption: string;
  showCompleted?: boolean;
}) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={caption}>
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Job</th>
            <th scope="col">Model</th>
            <th scope="col">Status</th>
            <th scope="col">Progress</th>
            <th scope="col">Created</th>
            {showCompleted && <th scope="col">Completed</th>}
            <th scope="col">
              <span className="visually-hidden">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.jobId}>
              <td>
                <code title={job.jobId}>{shortId(job.jobId)}</code>
              </td>
              <td>{job.modelKey}</td>
              <td>
                <JobStatusBadge status={job.status} />
                {job.errorCode && <span className="error-code">{job.errorCode}</span>}
              </td>
              <td>
                <div className="table-progress">
                  <ProgressBar
                    value={job.progress}
                    size="small"
                    tone={JOB_STATUS[job.status].tone}
                    label={`Job ${shortId(job.jobId)} progress`}
                  />
                  <span>{job.progress}%</span>
                </div>
              </td>
              <td>{formatDateTime(job.createdAt)}</td>
              {showCompleted && <td>{formatDateTime(job.completedAt)}</td>}
              <td>
                <Link
                  className="table-link"
                  to={`/detections/${job.jobId}`}
                  aria-label={`View details for job ${shortId(job.jobId)}`}
                >
                  View details
                  <Icon name="arrow" size={14} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
