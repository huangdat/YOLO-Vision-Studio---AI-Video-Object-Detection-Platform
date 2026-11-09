import { Link } from "react-router-dom";
import { countDetections, listDetections } from "../api/detections";
import { getModelVersions, listModels } from "../api/models";
import { DetectionTable } from "../components/DetectionTable";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatCard } from "../components/StatCard";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/StateViews";
import { StatusBadge } from "../components/StatusBadge";
import { useApiResource } from "../hooks/useApiResource";
import type { BackendStatus } from "../hooks/useBackendStatus";
import { formatNumber, sizeName } from "../lib/format";

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
  const [catalog, versions] = await Promise.all([
    listModels({}, signal),
    getModelVersions(signal),
  ]);
  const families = versions.versions.map((version) => {
    const models = catalog.models.filter((model) => model.version === version);
    return {
      version,
      registered: models.length,
      enabled: models.filter((model) => model.enabled).length,
      sizes: models.map((model) => model.modelSize),
    };
  });
  return {
    registered: catalog.models.length,
    enabled: catalog.models.filter((model) => model.enabled).length,
    families,
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

  return (
    <>
      <PageHeader
        title={
          <>
            YOLO Vision Studio<span className="title-dot">.</span>
          </>
        }
        description="AI-Powered Video Object Detection Platform"
        aside={
          <span className="phase-pill">
            <span />
            Phase 09 · Video preview
          </span>
        }
      />

      <section className="hero-panel" aria-labelledby="hero-title">
        <div className="hero-copy">
          <span className="hero-kicker">
            <Icon name="vision" size={15} />
            ASYNCHRONOUS VIDEO DETECTION
          </span>
          <h2 id="hero-title">
            Turn video into
            <br />
            <span>meaningful insight.</span>
          </h2>
          <p>
            Detection jobs run on YOLO workers in the background. Follow their
            progress, review measured results, and explore the registered model
            catalog.
          </p>
          <div className="hero-actions">
            <Link to="/detection" className="button-primary">
              Start a detection
              <Icon name="arrow" size={17} />
            </Link>
            <Link to="/history" className="button-secondary">
              View detection history
            </Link>
            <Link to="/models" className="button-secondary">
              Browse models
            </Link>
          </div>
        </div>
        <div className="vision-art" aria-hidden="true">
          <div className="art-orbit orbit-one" />
          <div className="art-orbit orbit-two" />
          <div className="art-grid" />
          <div className="art-corner top-left" />
          <div className="art-corner top-right" />
          <div className="art-corner bottom-left" />
          <div className="art-corner bottom-right" />
          <div className="vision-core">
            <Icon name="vision" size={80} />
          </div>
          <div className="art-node node-a">
            <Icon name="scan" size={20} />
          </div>
          <div className="art-node node-b">
            <Icon name="cpu" size={20} />
          </div>
          <div className="art-node node-c">
            <Icon name="layers" size={20} />
          </div>
          <div className="art-caption">
            <span />
            VISION ENGINE
          </div>
        </div>
      </section>

      <section className="dashboard-section" aria-labelledby="overview-title">
        <div className="section-heading">
          <div>
            <h2 id="overview-title">Detection overview</h2>
            <p>Totals across all detection jobs and registered models.</p>
          </div>
        </div>
        {counts.status === "error" && (
          <ErrorState
            title="Job statistics are unavailable"
            error={counts.error}
            onRetry={counts.reload}
          />
        )}
        {catalog.status === "error" && (
          <ErrorState
            title="Model statistics are unavailable"
            error={catalog.error}
            onRetry={catalog.reload}
          />
        )}
        <div className="stat-grid" aria-busy={loadingCounts || loadingCatalog}>
          {counts.status !== "error" && (
            <>
              <StatCard
                label="Total jobs"
                icon="history"
                tone="blue"
                value={loadingCounts ? <span className="skeleton-inline" /> : formatNumber(counts.data?.total)}
              />
              <StatCard
                label="Completed"
                icon="check"
                tone="green"
                value={loadingCounts ? <span className="skeleton-inline" /> : formatNumber(counts.data?.completed)}
              />
              <StatCard
                label="Failed"
                icon="alert"
                tone="red"
                value={loadingCounts ? <span className="skeleton-inline" /> : formatNumber(counts.data?.failed)}
              />
              <StatCard
                label="In progress"
                icon="activity"
                tone="purple"
                hint="Pending, queued, or processing"
                value={loadingCounts ? <span className="skeleton-inline" /> : formatNumber(counts.data?.inProgress)}
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
              value={loadingCatalog ? <span className="skeleton-inline" /> : formatNumber(catalog.data?.registered)}
            />
          )}
        </div>
      </section>

      <section className="panel" aria-labelledby="recent-title">
        <div className="section-heading">
          <div>
            <h2 id="recent-title">Recent detection activity</h2>
            <p>The {RECENT_JOBS} most recently created jobs.</p>
          </div>
          <Link to="/history" className="button-secondary">
            View all history
            <Icon name="arrow" size={14} />
          </Link>
        </div>
        <div className="panel-body">
          {recent.status === "loading" && (
            <LoadingSkeleton rows={RECENT_JOBS} label="Loading recent jobs" />
          )}
          {recent.status === "error" && (
            <ErrorState
              title="Recent jobs could not be loaded"
              error={recent.error}
              onRetry={recent.reload}
            />
          )}
          {recent.status === "success" &&
            (recent.data.content.length === 0 ? (
              <EmptyState icon="scan" title="No detection jobs yet">
                Jobs appear here once a video has been submitted for detection.
              </EmptyState>
            ) : (
              <DetectionTable
                jobs={recent.data.content}
                caption="Recent detection jobs"
                showCompleted={false}
              />
            ))}
        </div>
      </section>

      <div className="dashboard-columns">
        <section className="panel" aria-labelledby="families-title">
          <div className="section-heading">
            <div>
              <h2 id="families-title">Available YOLO families</h2>
              <p>Registered detection models by family.</p>
            </div>
            <Link to="/models" className="button-secondary">
              Models
              <Icon name="arrow" size={14} />
            </Link>
          </div>
          <div className="panel-body">
            {catalog.status === "loading" && (
              <LoadingSkeleton rows={4} label="Loading model families" />
            )}
            {catalog.status === "error" && (
              <p className="muted-text">Model families are unavailable.</p>
            )}
            {catalog.status === "success" &&
              (catalog.data.families.length === 0 ? (
                <EmptyState icon="models" title="No models are registered." />
              ) : (
                <ul className="family-list">
                  {catalog.data.families.map((family) => (
                    <li key={family.version}>
                      <div>
                        <strong>{family.version}</strong>
                        <span>
                          {family.sizes.map(sizeName).join(" · ")}
                        </span>
                      </div>
                      <span className="family-count">
                        {family.registered} models
                        <small>{family.enabled} enabled</small>
                      </span>
                    </li>
                  ))}
                </ul>
              ))}
          </div>
        </section>

        <section className="connection-panel" aria-labelledby="connection-title">
          <div className="section-heading">
            <div>
              <h2 id="connection-title">System connection</h2>
              <p>Live status from your backend, refreshed every 30 seconds.</p>
            </div>
            <button
              type="button"
              className="button-secondary"
              onClick={() => {
                void refresh();
              }}
              disabled={status.state === "checking"}
            >
              <Icon
                name="refresh"
                size={16}
                className={status.state === "checking" ? "spin" : ""}
              />
              Refresh
            </button>
          </div>
          <div className="connection-content">
            <div className="endpoint">
              <span className="method-label">GET</span>
              <code>/api/v1/system/info</code>
            </div>
            <div className="connection-status-row">
              <StatusBadge status={status} />
              {status.state === "connected" && (
                <span className="connection-version">
                  Spring Boot · v{status.info.version}
                </span>
              )}
            </div>
            {status.state === "connected" ? (
              <div className="connection-success">
                <span>
                  <Icon name="check" size={16} />
                  {status.info.application}
                </span>
                <span>
                  Last checked{" "}
                  {status.checkedAt.toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
            ) : status.state === "disconnected" ? (
              <p className="connection-error" role="alert">
                {status.message}
              </p>
            ) : (
              <p className="connection-pending">
                Checking the backend connection…
              </p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
