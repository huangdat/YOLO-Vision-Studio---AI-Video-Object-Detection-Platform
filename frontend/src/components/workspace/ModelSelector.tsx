import { useId } from "react";
import { sizeName } from "../../lib/format";
import { modelsForVersion, type ModelChoice } from "../../lib/modelSelection";
import type { ModelConfig } from "../../types/models";

/** Version and size come from the real catalog; the pair resolves to an actual record. */
export function ModelSelector({
  models,
  versions,
  choice,
  selected,
  error,
  disabled,
  onVersionChange,
  onSizeChange,
}: {
  models: ModelConfig[];
  versions: string[];
  choice: ModelChoice | null;
  selected: ModelConfig | undefined;
  error?: string;
  disabled?: boolean;
  onVersionChange: (version: string) => void;
  onSizeChange: (size: string) => void;
}) {
  const versionId = useId();
  const statusId = useId();
  const sizes = choice ? modelsForVersion(models, choice.version) : [];
  return (
    <div className="model-selector">
      <div className="form-field">
        <label htmlFor={versionId} className="field-label">
          YOLO version
        </label>
        <select
          id={versionId}
          className="select-input"
          value={choice?.version ?? ""}
          disabled={disabled}
          onChange={(event) => onVersionChange(event.target.value)}
        >
          {versions.map((version) => {
            const enabled = models.filter((model) => model.version === version && model.enabled).length;
            return (
              <option key={version} value={version}>
                {version} ({enabled === 0 ? "none enabled" : `${enabled} enabled`})
              </option>
            );
          })}
        </select>
      </div>

      <fieldset className="form-field size-options" disabled={disabled} aria-describedby={statusId}>
        <legend className="field-label">Model size</legend>
        <div className="segmented">
          {sizes.map((model) => (
            <label
              key={model.modelKey}
              className={`segment ${model.modelSize === choice?.size ? "checked" : ""} ${model.enabled ? "" : "is-disabled"}`}
            >
              <input
                type="radio"
                name="modelSize"
                value={model.modelSize}
                checked={model.modelSize === choice?.size}
                onChange={() => onSizeChange(model.modelSize)}
              />
              <span className="segment-title">{sizeName(model.modelSize)}</span>
              <span className="segment-meta">
                <code>{model.modelKey}</code>
                {!model.enabled && <span className="segment-tag">Disabled</span>}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div id={statusId} className={`model-status ${selected?.enabled ? "enabled" : "disabled"}`}>
        {selected ? (
          selected.enabled ? (
            <p>
              <strong>{selected.modelKey}</strong> is enabled for detection. Enablement is an
              administrative setting; the worker still needs the model&apos;s weights prepared and
              reports <code>MODEL_NOT_PREPARED</code> otherwise.
            </p>
          ) : (
            <p>
              <strong>{selected.modelKey}</strong> is disabled and cannot be submitted. An
              administrator must prepare and enable it first.
            </p>
          )
        ) : (
          <p>No model is selected.</p>
        )}
      </div>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
