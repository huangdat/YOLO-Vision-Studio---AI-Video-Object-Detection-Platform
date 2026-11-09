import { useEffect, useId, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { getModel, getModelVersions, listModels } from "../api/models";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Alert, EmptyState, ErrorState, LoadingSkeleton } from "../components/StateViews";
import { useApiResource } from "../hooks/useApiResource";
import { formatDateTime, MODEL_SIZES, sizeName } from "../lib/format";
import type { ModelCatalogFilter, ModelConfig } from "../types/models";

type EnabledFilter = "" | "true" | "false";

function readFilter(params: URLSearchParams, versions: string[] | undefined) {
  const version = params.get("version") ?? "";
  const size = params.get("size") ?? "";
  const enabled = (params.get("enabled") ?? "") as EnabledFilter;
  return {
    // Ignore unknown values from a hand-edited URL instead of sending them to the API.
    version: versions && !versions.includes(version) ? "" : version,
    size: MODEL_SIZES.includes(size) ? size : "",
    enabled: enabled === "true" || enabled === "false" ? enabled : ("" as EnabledFilter),
  };
}

export function Models() {
  const [params, setParams] = useSearchParams();
  const versions = useApiResource(getModelVersions, "model-versions");
  const filter = readFilter(params, versions.data?.versions);
  const query: ModelCatalogFilter = {
    version: filter.version || undefined,
    size: filter.size || undefined,
    enabled: filter.enabled === "" ? undefined : filter.enabled === "true",
  };
  const catalog = useApiResource(
    (signal) => listModels(query, signal),
    `models:${filter.version}:${filter.size}:${filter.enabled}`,
    { keepPreviousData: true },
  );
  const selectedKey = params.get("model");
  const selected = useApiResource(
    (signal) => getModel(selectedKey ?? "", signal),
    `model:${selectedKey}`,
    { enabled: Boolean(selectedKey) },
  );
  const filtering = Boolean(filter.version || filter.size || filter.enabled);
  const detailsRef = useRef<HTMLElement>(null);
  // Bring the details into view when a card is chosen; the grid can be long.
  useEffect(() => {
    if (!selectedKey) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    detailsRef.current?.scrollIntoView?.({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }, [selectedKey]);
  const ids = { version: useId(), size: useId(), enabled: useId() };

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Models"
        description="YOLO object detection models registered in your workspace."
      />

      <Alert tone="info">
        <p>
          <strong>Enabled</strong> models can be selected for new detections. Enabling is an
          administrative setting: it does not confirm that a worker has prepared its weights (a
          worker without them reports <code>MODEL_NOT_PREPARED</code>).
        </p>
      </Alert>

      <section className="card page-section" aria-labelledby="catalog-title">
        <div className="card-header">
          <div>
            <h2 id="catalog-title">Model catalog</h2>
            <p aria-live="polite">
              {catalog.status === "success"
                ? `${catalog.data.total} model${catalog.data.total === 1 ? "" : "s"} ${filtering ? (catalog.data.total === 1 ? "matches the filters" : "match the filters") : "registered"}`
                : "Loading the catalog…"}
            </p>
          </div>
        </div>

        <form className="filter-bar" onSubmit={(event) => event.preventDefault()}>
          <label htmlFor={ids.version}>
            Version
            <select
              id={ids.version}
              value={filter.version}
              onChange={(event) => update("version", event.target.value)}
              disabled={versions.status !== "success"}
            >
              <option value="">All versions</option>
              {versions.data?.versions.map((version) => (
                <option key={version} value={version}>
                  {version}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor={ids.size}>
            Size
            <select
              id={ids.size}
              value={filter.size}
              onChange={(event) => update("size", event.target.value)}
            >
              <option value="">All sizes</option>
              {MODEL_SIZES.map((size) => (
                <option key={size} value={size}>
                  {sizeName(size)} ({size})
                </option>
              ))}
            </select>
          </label>
          <label htmlFor={ids.enabled}>
            Status
            <select
              id={ids.enabled}
              value={filter.enabled}
              onChange={(event) => update("enabled", event.target.value)}
            >
              <option value="">Enabled and disabled</option>
              <option value="true">Enabled</option>
              <option value="false">Disabled</option>
            </select>
          </label>
          <button
            type="button"
            className="button-ghost"
            onClick={() => {
              const next = new URLSearchParams(params);
              ["version", "size", "enabled"].forEach((key) => next.delete(key));
              setParams(next, { replace: true });
            }}
            disabled={!filtering}
          >
            Clear filters
          </button>
        </form>

        <div aria-busy={catalog.status === "loading"}>
          {catalog.status === "error" && (
            <ErrorState
              title="The model catalog could not be loaded"
              error={catalog.error}
              onRetry={catalog.reload}
            />
          )}
          {catalog.status === "loading" && !catalog.data && (
            <LoadingSkeleton rows={4} label="Loading models" />
          )}
          {catalog.data &&
            catalog.status !== "error" &&
            (catalog.data.models.length === 0 ? (
              <EmptyState
                icon="models"
                title={filtering ? "No models match these filters." : "No models are registered."}
              />
            ) : (
              <ul className={`model-grid ${catalog.status === "loading" ? "is-stale" : ""}`}>
                {catalog.data.models.map((model) => (
                  <ModelCard
                    key={model.id}
                    model={model}
                    selected={model.modelKey === selectedKey}
                    onSelect={() => update("model", model.modelKey)}
                  />
                ))}
              </ul>
            ))}
        </div>
      </section>

      {selectedKey && (
        <section
          ref={detailsRef}
          className="card page-section model-details"
          aria-labelledby="model-details-title"
        >
          <div className="card-header">
            <div>
              <h2 id="model-details-title">Model details</h2>
              <p>
                <code>{selectedKey}</code>
              </p>
            </div>
            <button type="button" className="button-ghost" onClick={() => update("model", "")}>
              <Icon name="close" size={14} />
              Close
            </button>
          </div>
          <div>
            {selected.status === "loading" && <LoadingSkeleton rows={3} label="Loading model details" />}
            {selected.status === "error" && (
              <ErrorState
                title={selected.error.status === 404 ? "Model not found" : "Model details could not be loaded"}
                error={selected.error}
                onRetry={selected.reload}
              />
            )}
            {selected.status === "success" && (
              <dl className="detail-list">
                <div><dt>Model key</dt><dd><code>{selected.data.modelKey}</code></dd></div>
                <div><dt>Version</dt><dd>{selected.data.version}</dd></div>
                <div><dt>Size</dt><dd>{sizeName(selected.data.modelSize)} ({selected.data.modelSize})</dd></div>
                <div><dt>Task</dt><dd>{selected.data.taskType}</dd></div>
                <div><dt>Checkpoint</dt><dd><code>{selected.data.weightsFilename}</code></dd></div>
                <div><dt>Administrative status</dt><dd>{selected.data.enabled ? "Enabled" : "Disabled"}</dd></div>
                <div><dt>Registered</dt><dd>{formatDateTime(selected.data.createdAt)}</dd></div>
                <div><dt>Last updated</dt><dd>{formatDateTime(selected.data.updatedAt)}</dd></div>
              </dl>
            )}
          </div>
        </section>
      )}
    </>
  );
}

function ModelCard({
  model,
  selected,
  onSelect,
}: {
  model: ModelConfig;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li className={`model-card ${selected ? "selected" : ""}`}>
      <div className="model-card-top">
        <h3>
          {model.version} {sizeName(model.modelSize)}
        </h3>
        <span className={`availability ${model.enabled ? "enabled" : "disabled"}`}>
          <span className="status-dot" aria-hidden="true" />
          {model.enabled ? "Enabled" : "Disabled"}
        </span>
      </div>
      <p className="model-key">
        Model <code>{model.modelKey}</code>
      </p>
      <button
        type="button"
        className="button-secondary model-card-action"
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={`Details for ${model.modelKey}`}
      >
        View details
      </button>
    </li>
  );
}
