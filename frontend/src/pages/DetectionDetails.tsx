import { useEffect, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { getDetection, getDetectionResult, isJobId } from "../api/detections";
import { Icon } from "../components/Icon";
import { JobStatusBadge } from "../components/JobStatusBadge";
import { PageHeader } from "../components/PageHeader";
import { ProgressBar } from "../components/ProgressBar";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/StateViews";
import { useApiResource, type Resource } from "../hooks/useApiResource";
import {
  isNewerSnapshot,
  useDetectionProgress,
  type ProgressConnection,
} from "../hooks/useDetectionProgress";
import {
  classLabel,
  formatDateTime,
  formatDuration,
  formatNumber,
  shortId,
} from "../lib/format";
import { isTerminal, JOB_STATUS } from "../lib/jobStatus";
import type {
  DetectionJob,
  DetectionProgressEvent,
  DetectionResultMetadata,
} from "../types/detections";

const CONNECTION_LABEL: Record<ProgressConnection, string> = {
  idle: "",
  connecting: "Connecting to live updates…",
  live: "Live updates",
  reconnecting: "Reconnecting to live updates…",
  polling: "Live updates unavailable; checking every few seconds",
  closed: "",
};

export function DetectionDetails() {
  const { jobId } = useParams();
  const validId = isJobId(jobId);
  const job = useApiResource(
    (signal) => getDetection(jobId ?? "", signal),
    `job:${jobId}`,
    { enabled: validId },
  );
  const loaded = job.data;
  const { event, connection } = useDetectionProgress(jobId, {
    enabled: Boolean(loaded) && !isTerminal(loaded?.status ?? "COMPLETED"),
  });

  // The persisted job is the base snapshot; a newer live event overrides it.
  const base: DetectionProgressEvent | null = loaded
    ? {
        jobId: loaded.jobId,
        status: loaded.status,
        progress: loaded.progress,
        message: loaded.errorMessage,
        errorCode: loaded.errorCode,
        timestamp: loaded.updatedAt,
      }
    : null;
  const current = event && isNewerSnapshot(event, base) ? event : base;

  // A terminal event carries no completion time or full error text: reload the job once.
  const reloadJob = job.reload;
  const terminalEvent = event && isTerminal(event.status) ? event.status : null;
  useEffect(() => {
    if (terminalEvent && loaded && loaded.status !== terminalEvent) reloadJob();
  }, [terminalEvent, loaded, reloadJob]);

  const completed = loaded?.status === "COMPLETED";
  const result = useApiResource(
    (signal) => getDetectionResult(jobId ?? "", signal),
    `result:${jobId}:${completed}`,
    { enabled: validId && completed },
  );

  if (!validId) {
    return (
      <DetailsShell title="Detection job">
        <ErrorState
          title="Invalid job ID"
          error={new ApiError("http", "The address does not contain a valid detection job ID.")}
        />
      </DetailsShell>
    );
  }
  if (job.status === "error" && !loaded) {
    const notFound = job.error.status === 404;
    return (
      <DetailsShell title="Detection job">
        <ErrorState
          title={notFound ? "Detection job not found" : "The job could not be loaded"}
          error={job.error}
          onRetry={job.reload}
        />
      </DetailsShell>
    );
  }
  if (!loaded || !current) {
    return (
      <DetailsShell title="Detection job">
        <LoadingSkeleton rows={6} label="Loading the detection job" />
      </DetailsShell>
    );
  }

  const meta = JOB_STATUS[current.status];
  return (
    <DetailsShell title={`Job ${shortId(loaded.jobId)}`}>
      <section className="panel job-status-panel" aria-labelledby="status-title">
        <div className="section-heading">
          <div>
            <h2 id="status-title">Processing status</h2>
            <p>
              <code className="full-id">{loaded.jobId}</code>
            </p>
          </div>
          <JobStatusBadge status={current.status} />
        </div>
        <div className="panel-body">
          <div className="stage-row">
            <span className="stage-label" aria-live="polite">
              {meta.description}
            </span>
            <strong>{current.progress}%</strong>
          </div>
          <ProgressBar value={current.progress} tone={meta.tone} label="Job progress" />
          {connection !== "idle" && connection !== "closed" && (
            <p className={`connection-note ${connection}`}>
              <span className="status-dot" aria-hidden="true" />
              {CONNECTION_LABEL[connection]}
            </p>
          )}
          {current.status === "FAILED" && (
            <div className="failure-box" role="alert">
              <Icon name="alert" size={18} />
              <div>
                <strong>{loaded.errorCode ?? current.errorCode ?? "FAILED"}</strong>
                <p>{loaded.errorMessage ?? current.message ?? "Detection failed."}</p>
              </div>
            </div>
          )}
          {current.status === "CANCELLED" && (
            <p className="muted-text">This job was cancelled and will not produce results.</p>
          )}
        </div>
      </section>

      <div className="dashboard-columns">
        <JobConfiguration job={loaded} />
        <JobTimeline job={loaded} />
      </div>

      {completed && <ResultPanel result={result} />}
    </DetailsShell>
  );
}

function DetailsShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <PageHeader
        eyebrow="DETECTION JOB"
        title={title}
        aside={
          <Link to="/history" className="button-secondary">
            <Icon name="chevronLeft" size={14} />
            Back to history
          </Link>
        }
      />
      {children}
    </>
  );
}

function JobConfiguration({ job }: { job: DetectionJob }) {
  return (
    <section className="panel" aria-labelledby="config-title">
      <div className="section-heading">
        <div>
          <h2 id="config-title">Configuration</h2>
        </div>
      </div>
      <dl className="detail-list panel-body">
        <div><dt>Model</dt><dd><code>{job.modelKey}</code> · {job.modelVersion}</dd></div>
        <div><dt>Confidence threshold</dt><dd>{job.confidence}</dd></div>
        <div><dt>Image size</dt><dd>{job.imageSize} px</dd></div>
        <div>
          <dt>Selected class IDs</dt>
          <dd className="chip-list">
            {job.classes.map((id) => <span key={id} className="chip">{id}</span>)}
          </dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            {job.videoUrl ? (
              <a href={job.videoUrl} target="_blank" rel="noreferrer noopener" className="text-link">
                YouTube video
                <Icon name="external" size={13} />
              </a>
            ) : (
              "Local development source"
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function JobTimeline({ job }: { job: DetectionJob }) {
  return (
    <section className="panel" aria-labelledby="timeline-title">
      <div className="section-heading">
        <div>
          <h2 id="timeline-title">Timeline</h2>
        </div>
      </div>
      <dl className="detail-list panel-body">
        <div><dt>Created</dt><dd>{formatDateTime(job.createdAt)}</dd></div>
        <div><dt>Started</dt><dd>{formatDateTime(job.startedAt)}</dd></div>
        <div><dt>Completed</dt><dd>{formatDateTime(job.completedAt)}</dd></div>
        <div><dt>Last update</dt><dd>{formatDateTime(job.updatedAt)}</dd></div>
      </dl>
    </section>
  );
}

function ResultPanel({
  result,
}: {
  result: Resource<DetectionResultMetadata> & { reload: () => void };
}) {
  return (
    <section className="panel" aria-labelledby="result-title">
      <div className="section-heading">
        <div>
          <h2 id="result-title">Detection results</h2>
          <p>
            Counts are bounding-box detections summed across all processed frames, not
            unique objects. An object visible in many frames is counted in each frame.
          </p>
        </div>
      </div>
      <div className="panel-body">
        {result.status === "loading" && <LoadingSkeleton rows={4} label="Loading results" />}
        {result.status === "error" && (
          <ErrorState title="Results could not be loaded" error={result.error} onRetry={result.reload} />
        )}
        {result.status === "success" && <ResultStatistics result={result.data} />}
      </div>
    </section>
  );
}

function ResultStatistics({ result }: { result: DetectionResultMetadata }) {
  const classes = Object.entries(result.detectionSummary).sort((a, b) => b[1] - a[1]);
  const largest = classes.length ? classes[0][1] : 0;
  return (
    <>
      <dl className="result-metrics">
        <div><dt>Model used</dt><dd><code>{result.modelKey}</code></dd></div>
        <div><dt>Frames processed</dt><dd>{formatNumber(result.totalFrames)}</dd></div>
        <div><dt>Processing time</dt><dd>{formatDuration(result.processingTimeMs)}</dd></div>
        <div><dt>Detection events</dt><dd>{formatNumber(result.totalDetections)}</dd></div>
      </dl>

      <h3 className="subheading">Detection events by class</h3>
      {classes.length === 0 ? (
        <EmptyState icon="scan" title="No objects of the selected classes were detected." />
      ) : (
        <ul className="class-bars">
          {classes.map(([label, count]) => (
            <li key={label}>
              <div className="class-bar-label">
                <span>{classLabel(label)} detection events</span>
                <strong>{count.toLocaleString()}</strong>
              </div>
              <span className="class-bar-track" aria-hidden="true">
                <span style={{ width: `${largest ? (count / largest) * 100 : 0}%` }} />
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="info-note">
        <Icon name="film" size={15} />
        <span>
          {result.outputVideoAvailable
            ? "The annotated video is stored. Video preview and download will be available in a future phase."
            : "No annotated video was recorded for this job."}
        </span>
      </p>
    </>
  );
}
