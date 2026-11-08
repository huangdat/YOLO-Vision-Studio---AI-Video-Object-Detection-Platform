import { useId } from "react";
import { useSearchParams } from "react-router-dom";
import { listDetections } from "../api/detections";
import { listModels } from "../api/models";
import { DetectionTable } from "../components/DetectionTable";
import { PageHeader } from "../components/PageHeader";
import { PaginationControls } from "../components/PaginationControls";
import { EmptyState, ErrorState, LoadingSkeleton } from "../components/StateViews";
import { useApiResource } from "../hooks/useApiResource";
import { JOB_STATUS } from "../lib/jobStatus";
import { DETECTION_JOB_STATUSES, type DetectionJobStatus } from "../types/detections";

export const PAGE_SIZES = [10, 25, 50] as const;

function readQuery(params: URLSearchParams) {
  const page = Number.parseInt(params.get("page") ?? "0", 10);
  const size = Number.parseInt(params.get("size") ?? "10", 10);
  const status = params.get("status") ?? "";
  const model = params.get("model") ?? "";
  return {
    page: Number.isInteger(page) && page >= 0 ? page : 0,
    size: (PAGE_SIZES as readonly number[]).includes(size) ? size : 10,
    status: DETECTION_JOB_STATUSES.includes(status as DetectionJobStatus)
      ? (status as DetectionJobStatus)
      : undefined,
    model: /^[a-z0-9][a-z0-9_-]{0,63}$/.test(model) ? model : undefined,
  };
}

export function History() {
  const [params, setParams] = useSearchParams();
  const query = readQuery(params);
  const history = useApiResource(
    (signal) =>
      listDetections(
        { page: query.page, size: query.size, status: query.status, modelKey: query.model },
        signal,
      ),
    `history:${query.page}:${query.size}:${query.status ?? ""}:${query.model ?? ""}`,
    { keepPreviousData: true },
  );
  const models = useApiResource((signal) => listModels({}, signal), "history-models");
  const filtering = Boolean(query.status || query.model);
  const ids = { status: useId(), model: useId(), size: useId() };

  /** Changing a filter or page size returns to the first page. */
  const update = (changes: Record<string, string | undefined>, resetPage = true) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([key, value]) => {
      if (value) next.set(key, value);
      else next.delete(key);
    });
    if (resetPage) next.delete("page");
    setParams(next);
  };

  const page = history.data;
  return (
    <>
      <PageHeader
        title="History"
        description="Every detection job, newest first. Select a job to see its progress and results."
      />

      <section className="panel" aria-labelledby="history-title">
        <div className="section-heading">
          <div>
            <h2 id="history-title">Detection jobs</h2>
            <p aria-live="polite">
              {page
                ? `${page.totalElements.toLocaleString()} job${page.totalElements === 1 ? "" : "s"} ${filtering ? (page.totalElements === 1 ? "matches the filters" : "match the filters") : "in total"}`
                : "Loading jobs…"}
            </p>
          </div>
        </div>

        <form className="filter-bar" onSubmit={(event) => event.preventDefault()}>
          <label htmlFor={ids.status}>
            Status
            <select
              id={ids.status}
              value={query.status ?? ""}
              onChange={(event) => update({ status: event.target.value })}
            >
              <option value="">All statuses</option>
              {DETECTION_JOB_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {JOB_STATUS[status].label}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor={ids.model}>
            Model
            <select
              id={ids.model}
              value={query.model ?? ""}
              onChange={(event) => update({ model: event.target.value })}
            >
              <option value="">All models</option>
              {query.model &&
                !models.data?.models.some((model) => model.modelKey === query.model) && (
                  <option value={query.model}>{query.model}</option>
                )}
              {models.data?.models.map((model) => (
                <option key={model.modelKey} value={model.modelKey}>
                  {model.modelKey}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor={ids.size}>
            Rows per page
            <select
              id={ids.size}
              value={query.size}
              onChange={(event) => update({ size: event.target.value === "10" ? "" : event.target.value })}
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button-secondary"
            onClick={() => update({ status: undefined, model: undefined })}
            disabled={!filtering}
          >
            Clear filters
          </button>
        </form>

        <div className="panel-body" aria-busy={history.status === "loading"}>
          {history.status === "error" && (
            <ErrorState
              title="Detection history could not be loaded"
              error={history.error}
              onRetry={history.reload}
            />
          )}
          {history.status === "loading" && !page && (
            <LoadingSkeleton rows={6} label="Loading detection history" />
          )}
          {page && history.status !== "error" && (
            <>
              {page.content.length === 0 ? (
                page.totalElements > 0 ? (
                  <EmptyState icon="history" title="This page is empty.">
                    <button
                      type="button"
                      className="button-secondary"
                      onClick={() => update({}, true)}
                    >
                      Go to the first page
                    </button>
                  </EmptyState>
                ) : (
                  <EmptyState
                    icon="history"
                    title={filtering ? "No jobs match these filters." : "No detection jobs yet."}
                  >
                    {!filtering &&
                      "Jobs appear here once a video has been submitted for detection."}
                  </EmptyState>
                )
              ) : (
                <div className={history.status === "loading" ? "is-stale" : ""}>
                  <DetectionTable jobs={page.content} caption="Detection job history" />
                </div>
              )}
              <PaginationControls
                page={page.page}
                totalPages={page.totalPages}
                totalElements={page.totalElements}
                pageSize={page.size}
                disabled={history.status === "loading"}
                onPageChange={(next) => update({ page: next > 0 ? String(next) : undefined }, false)}
              />
            </>
          )}
        </div>
      </section>
    </>
  );
}
