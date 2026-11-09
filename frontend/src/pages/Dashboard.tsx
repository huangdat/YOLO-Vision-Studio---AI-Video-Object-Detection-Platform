import { Link } from "react-router-dom";
import { countDetections, listDetections } from "../api/detections";
import { listModels } from "../api/models";
import { DetectionTable } from "../components/DetectionTable";
import { Icon } from "../components/Icon";
import { StatCard } from "../components/StatCard";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/StateViews";
import { StatusBadge } from "../components/StatusBadge";
import { useApiResource } from "../hooks/useApiResource";
import type { BackendStatus } from "../hooks/useBackendStatus";
import { formatNumber } from "../lib/format";

const RECENT_JOBS = 5;

/**
 * Job counts come from pagination metadata of size=1 queries (totalElements per status),
 * never from the rows of one page, so they stay correct for any history size.
 */
async function loadJobCounts(signal: AbortSignal) {
  const [total, completed, failed, cancelled] = await Promise.all([
    countDetections({}, signal),
    countDetections({ status: "COMPLETED" }, signal),
    countDetections({ status: "FAILED" }, signal),
    countDetections({ status: "CANCELLED" }, signal),
  ]);
  return {
    total,
    completed,
    failed,
    // Separate count queries are not one snapshot; never show a negative number.
    inProgress: Math.max(0, total - completed - failed - cancelled),
  };
}

async function loadCatalog(signal: AbortSignal) {
  const catalog = await listModels({}, signal);
  return {
    registered: catalog.models.length,
    enabled: catalog.models.filter((model) => model.enabled).length,
  };
}

export function Dashboard({
  status,
  refresh,
}: {
  status: BackendStatus;
  refresh: () => Promise<void>;
}) {
  const counts = useApiResource(loadJobCounts, "job-counts");
  const catalog = useApiResource(loadCatalog, "model-catalog");
  const recent = useApiResource(
    (signal) => listDetections({ page: 0, size: RECENT_JOBS }, signal),
    "recent-jobs",
  );
  const loadingCounts = counts.status === "loading";
  const loadingCatalog = catalog.status === "loading";
  const pending = <span className="skeleton-inline" aria-hidden="true" />;

  return (
    <>
      <section className="welcome" aria-labelledby="welcome-title">
        <div>
          <h1 id="welcome-title">Welcome to YOLO Vision Studio</h1>
          <p>
            Detect and analyze objects in YouTube videos with YOLO models. Submit a video, follow
            its progress, then watch and download the annotated result.
          </p>
        </div>
        <div className="welcome-actions">
          <Link to="/detection" className="button-primary button-large">
            Start new detection
            <Icon name="arrow" size={18} />
          </Link>
          <Link to="/history" className="button-secondary button-large">
            View history
          </Link>
        </div>
      </section>

      <section className="page-section" aria-labelledby="overview-title">
        <h2 id="overview-title" className="section-title">
          Overview
        </h2>
        {counts.status === "error" && (
          <ErrorState title="Job statistics are unavailable" error={counts.error} onRetry={counts.reload} />
        )}
        {catalog.status === "error" && (
          <ErrorState title="Model statistics are unavailable" error={catalog.error} onRetry={catalog.reload} />
        )}
        <div className="stat-grid" aria-busy={loadingCounts || loadingCatalog}>
          {counts.status !== "error" && (
            <>
              <StatCard
                label="Total jobs"
                icon="history"
                tone="blue"
                value={loadingCounts ? pending : formatNumber(counts.data?.total)}
              />
              <StatCard
                label="Completed"
                icon="check"
                tone="green"
                value={loadingCounts ? pending : formatNumber(counts.data?.completed)}
              />
              <StatCard
                label="In progress"
                icon="activity"
                tone="purple"
                hint="Pending, queued, or processing"
                value={loadingCounts ? pending : formatNumber(counts.data?.inProgress)}
              />
              <StatCard
                label="Failed"
                icon="alert"
                tone="red"
                value={loadingCounts ? pending : formatNumber(counts.data?.failed)}
              />
            </>
          )}
          {catalog.status !== "error" && (
            <StatCard
              label="YOLO models"
              icon="models"
              tone="teal"
              hint={
                loadingCatalog
                  ? "Loading the catalog…"
                  : `${formatNumber(catalog.data?.enabled)} enabled for detection`
              }
              value={loadingCatalog ? pending : formatNumber(catalog.data?.registered)}
            />
          )}
        </div>
      </section>

      <section className="card page-section" aria-labelledby="recent-title">
        <div className="card-header">
          <div>
            <h2 id="recent-title">Recent detections</h2>
            <p>The {RECENT_JOBS} most recently created jobs.</p>
          </div>
          <Link to="/history" className="button-ghost">
            View all history
            <Icon name="arrow" size={16} />
          </Link>
        </div>
        {recent.status === "loading" && <LoadingSkeleton rows={RECENT_JOBS} label="Loading recent jobs" />}
        {recent.status === "error" && (
          <ErrorState title="Recent jobs could not be loaded" error={recent.error} onRetry={recent.reload} />
        )}
        {recent.status === "success" &&
          (recent.data.content.length === 0 ? (
            <EmptyState icon="scan" title="No detection jobs yet">
              <p>Your detections will appear here after you submit a video.</p>
              <Link to="/detection" className="button-primary">
                Start your first detection
              </Link>
            </EmptyState>
          ) : (
            <DetectionTable jobs={recent.data.content} caption="Recent detection jobs" />
          ))}
      </section>

      <section className="system-strip" aria-labelledby="connection-title">
        <h2 id="connection-title" className="visually-hidden">
          System connection
        </h2>
        <div className="system-strip-status">
          <StatusBadge status={status} />
          {status.state === "connected" && (
            <span className="muted-text">
              Spring Boot · v{status.info.version} · checked{" "}
              {status.checkedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          {status.state === "disconnected" && (
            <span className="text-danger" role="alert">
              {status.message}
            </span>
          )}
        </div>
        <button
          type="button"
          className="button-ghost"
          onClick={() => {
            void refresh();
          }}
          disabled={status.state === "checking"}
        >
          <Icon name="refresh" size={16} className={status.state === "checking" ? "spin" : ""} />
          Refresh
        </button>
      </section>
    </>
  );
}
