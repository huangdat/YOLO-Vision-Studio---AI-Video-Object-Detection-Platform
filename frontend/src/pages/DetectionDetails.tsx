import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { detectionVideoDownloadUrl, resultJsonDownloadUrl } from "../api/artifacts";
import { ApiError } from "../api/client";
import { getDetection, getDetectionResult, isJobId } from "../api/detections";
import { Icon } from "../components/Icon";
import { JobStatusBadge } from "../components/JobStatusBadge";
import { PageHeader } from "../components/PageHeader";
import { DetectionVideoPlayer } from "../components/results/DetectionVideoPlayer";
import { ResultJsonViewer } from "../components/results/ResultJsonViewer";
import { ProgressBar } from "../components/ProgressBar";
import { Alert, Disclosure, EmptyState, ErrorState, LoadingSkeleton } from "../components/StateViews";
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
import { className } from "../lib/cocoClasses";
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

/** True when the workspace navigated here right after the backend accepted this job. */
function wasJustSubmitted(state: unknown, jobId: string | undefined): boolean {
  if (typeof state !== "object" || state === null || !("submitted" in state)) return false;
  const submitted: unknown = state.submitted;
  return (
    typeof submitted === "object" &&
    submitted !== null &&
    "jobId" in submitted &&
    submitted.jobId === jobId
  );
}

export function DetectionDetails() {
  const { jobId } = useParams();
  const validId = isJobId(jobId);
  const justSubmitted = wasJustSubmitted(useLocation().state, jobId);
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
  const headline = statusHeadline(current.status, meta.description);
  return (
    <DetailsShell title={`Job ${shortId(loaded.jobId)}`}>
      {justSubmitted && (
        <Alert tone="success" role="status">
          <p>
            Job submitted. The backend accepted it and queued it for the AI worker; progress
            updates appear below.{" "}
            <Link to="/detection" className="text-link">
              Start another detection
            </Link>
          </p>
        </Alert>
      )}

      <section className={`card status-card status-${meta.tone}`} aria-labelledby="status-title">
        <div className="status-card-top">
          <div>
            <h2 id="status-title">{headline.title}</h2>
            <p className="status-card-text" aria-live="polite">
              {headline.text}
            </p>
          </div>
          <JobStatusBadge status={current.status} />
        </div>
        {current.status !== "FAILED" && current.status !== "CANCELLED" && (
          <div className="status-progress">
            <div className="stage-row">
              <span>Progress</span>
              <strong>{current.progress}%</strong>
            </div>
            <ProgressBar value={current.progress} tone={meta.tone} label="Job progress" />
          </div>
        )}
        {(current.status === "FAILED" || current.status === "CANCELLED") && (
          <ProgressBar value={current.progress} tone={meta.tone} label="Job progress" size="small" />
        )}
        {connection !== "idle" && connection !== "closed" && (
          <p className={`connection-note ${connection}`}>
            <span className="status-dot" aria-hidden="true" />
            {CONNECTION_LABEL[connection]}
          </p>
        )}
        {current.status === "FAILED" && (
          <Alert tone="error" role="alert">
            <p>{loaded.errorMessage ?? current.message ?? "Detection failed."}</p>
            <p className="error-code-line">
              Error code <code>{loaded.errorCode ?? current.errorCode ?? "FAILED"}</code>
            </p>
          </Alert>
        )}
      </section>

      {completed && <ResultPanel jobId={loaded.jobId} result={result} />}

      <JobSettings job={loaded} />

      <section className="card page-section" aria-label="Technical details">
        <Disclosure label="Technical details" summary="Job ID, class IDs, and update time">
          <dl className="detail-list">
            <div>
              <dt>Job ID</dt>
              <dd>
                <code className="full-id">{loaded.jobId}</code>
              </dd>
            </div>
            <div>
              <dt>Class IDs</dt>
              <dd>{loaded.classes.join(", ")}</dd>
            </div>
            <div>
              <dt>Last update</dt>
              <dd>{formatDateTime(loaded.updatedAt)}</dd>
            </div>
          </dl>
        </Disclosure>
      </section>
    </DetailsShell>
  );
}

/** Plain-language heading for each lifecycle state; the badge keeps the exact status. */
function statusHeadline(status: DetectionJob["status"], description: string) {
  switch (status) {
    case "COMPLETED":
      return { title: "Detection complete", text: "Your video has been processed successfully." };
    case "FAILED":
      return { title: "We couldn't process this video", text: "The job stopped before producing results." };
    case "CANCELLED":
      return { title: "Detection cancelled", text: "This job was cancelled and will not produce results." };
    default:
      return { title: "Processing your video", text: description };
  }
}

function DetailsShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <PageHeader
        title={title}
        aside={
          <Link to="/history" className="button-ghost">
            <Icon name="chevronLeft" size={16} />
            Back to history
          </Link>
        }
      />
      <div className="details-stack">{children}</div>
    </>
  );
}

function JobSettings({ job }: { job: DetectionJob }) {
  return (
    <section className="card" aria-labelledby="config-title">
      <h2 id="config-title" className="card-title">
        Job settings
      </h2>
      <dl className="detail-grid">
        <div>
          <dt>Model</dt>
          <dd>
            <code>{job.modelKey}</code> · {job.modelVersion}
          </dd>
        </div>
        <div>
          <dt>Confidence threshold</dt>
          <dd>{job.confidence}</dd>
        </div>
        <div>
          <dt>Image size</dt>
          <dd>{job.imageSize} px</dd>
        </div>
        <div>
          <dt>Objects</dt>
          <dd>{job.classes.map((id) => classLabel(className(id))).join(", ")}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            {job.videoUrl ? (
              <a href={job.videoUrl} target="_blank" rel="noreferrer noopener" className="text-link">
                YouTube video
                <Icon name="external" size={14} />
              </a>
            ) : (
              "Local development source"
            )}
          </dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatDateTime(job.createdAt)}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{formatDateTime(job.startedAt)}</dd>
        </div>
        <div>
          <dt>Completed</dt>
          <dd>{formatDateTime(job.completedAt)}</dd>
        </div>
      </dl>
    </section>
  );
}

function ResultPanel({
  jobId,
  result,
}: {
  jobId: string;
  result: Resource<DetectionResultMetadata> & { reload: () => void };
}) {
  return (
    <>
      {result.status === "success" && <ResultMedia jobId={jobId} result={result.data} />}
      <ResultStatisticsPanel result={result} />
      {result.status === "success" && result.data.resultMetadataAvailable && (
        <section className="card" aria-labelledby="json-title">
          <div className="card-header">
            <div>
              <h2 id="json-title">Result JSON</h2>
              <p>The raw result file stored by the AI worker.</p>
            </div>
          </div>
          <ResultJsonViewer jobId={jobId} />
        </section>
      )}
    </>
  );
}

/** Video preview and downloads; only for completed jobs whose metadata records a video. */
function ResultMedia({ jobId, result }: { jobId: string; result: DetectionResultMetadata }) {
  const [missing, setMissing] = useState(false);
  const videoAvailable = result.outputVideoAvailable && !missing;
  return (
    <section className="card media-card" aria-labelledby="video-title">
      <h2 id="video-title" className="card-title">
        Detected video
      </h2>
      {result.outputVideoAvailable ? (
        <DetectionVideoPlayer jobId={jobId} onMissing={() => setMissing(true)} />
      ) : (
        <EmptyState icon="film" title="No annotated video was recorded for this job." />
      )}
      {(videoAvailable || result.resultMetadataAvailable) && (
        <div className="media-actions">
          {videoAvailable && (
            <a className="button-primary" href={detectionVideoDownloadUrl(jobId)} download>
              <Icon name="download" size={18} />
              Download detected video
            </a>
          )}
          {result.resultMetadataAvailable && (
            <a className="button-secondary" href={resultJsonDownloadUrl(jobId)} download>
              <Icon name="download" size={18} />
              Download JSON
            </a>
          )}
        </div>
      )}
    </section>
  );
}

function ResultStatisticsPanel({
  result,
}: {
  result: Resource<DetectionResultMetadata> & { reload: () => void };
}) {
  return (
    <section className="card" aria-labelledby="result-title">
      <div className="card-header">
        <div>
          <h2 id="result-title">Detection summary</h2>
          <p>
            Counts are detections summed across all processed frames, not unique objects. An
            object visible in many frames is counted in each frame.
          </p>
        </div>
      </div>
      {result.status === "loading" && <LoadingSkeleton rows={4} label="Loading results" />}
      {result.status === "error" && (
        <ErrorState title="Results could not be loaded" error={result.error} onRetry={result.reload} />
      )}
      {result.status === "success" && <ResultStatistics result={result.data} />}
    </section>
  );
}

function ResultStatistics({ result }: { result: DetectionResultMetadata }) {
  const classes = Object.entries(result.detectionSummary).sort((a, b) => b[1] - a[1]);
  const largest = classes.length ? classes[0][1] : 0;
  return (
    <>
      <dl className="result-metrics">
        <div><dt>Frames processed</dt><dd>{formatNumber(result.totalFrames)}</dd></div>
        <div><dt>Detection events</dt><dd>{formatNumber(result.totalDetections)}</dd></div>
        <div><dt>Processing time</dt><dd>{formatDuration(result.processingTimeMs)}</dd></div>
        <div><dt>Model used</dt><dd><code>{result.modelKey}</code></dd></div>
      </dl>

      <h3 className="subheading">Objects detected</h3>
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
    </>
  );
}
