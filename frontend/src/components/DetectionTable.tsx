import { Link } from "react-router-dom";
import { formatDateTime, shortId } from "../lib/format";
import { JOB_STATUS } from "../lib/jobStatus";
import type { DetectionJobSummary } from "../types/detections";
import { Icon } from "./Icon";
import { JobStatusBadge } from "./JobStatusBadge";
import { ProgressBar } from "./ProgressBar";

/**
 * Job rows (history and recent activity). On narrow screens each row becomes a stacked
 * card; the data-label attributes provide the column names there.
 */
export function DetectionTable({
  jobs,
  caption,
  showCompleted = false,
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
              <td data-label="Job">
                <code className="job-id" title={job.jobId}>
                  {shortId(job.jobId)}
                </code>
              </td>
              <td data-label="Model">{job.modelKey}</td>
              <td data-label="Status">
                <span className="status-cell">
                  <JobStatusBadge status={job.status} />
                  {job.errorCode && <span className="error-code">{job.errorCode}</span>}
                </span>
              </td>
              <td data-label="Progress">
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
              <td data-label="Created">{formatDateTime(job.createdAt)}</td>
              {showCompleted && <td data-label="Completed">{formatDateTime(job.completedAt)}</td>}
              <td className="cell-action">
                <Link
                  className="table-link"
                  to={`/detections/${job.jobId}`}
                  aria-label={`View details for job ${shortId(job.jobId)}`}
                >
                  View details
                  <Icon name="arrow" size={15} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
