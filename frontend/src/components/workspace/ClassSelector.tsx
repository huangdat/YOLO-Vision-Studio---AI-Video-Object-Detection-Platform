import { useId, useState } from "react";
import {
  ALL_CLASS_IDS,
  COCO_CLASSES,
  className,
  VEHICLE_CLASS_IDS,
} from "../../lib/cocoClasses";
import { classLabel } from "../../lib/format";

/** COCO class picker with presets and search; emits sorted, duplicate-free IDs. */
export function ClassSelector({
  selected,
  error,
  disabled,
  onChange,
}: {
  selected: number[];
  error?: string;
  disabled?: boolean;
  onChange: (classes: number[]) => void;
}) {
  const [query, setQuery] = useState("");
  const searchId = useId();
  const countId = useId();
  const errorId = useId();
  const chosen = new Set(selected);
  const term = query.trim().toLowerCase();
  const visible = term
    ? COCO_CLASSES.filter((item) => item.name.includes(term) || String(item.id) === term)
    : COCO_CLASSES;
  const emit = (ids: Iterable<number>) => onChange([...new Set(ids)].sort((a, b) => a - b));
  const toggle = (id: number) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    emit(next);
  };
  const isVehiclePreset =
    selected.length === VEHICLE_CLASS_IDS.length && VEHICLE_CLASS_IDS.every((id) => chosen.has(id));

  return (
    <fieldset
      className="form-field class-selector"
      disabled={disabled}
      aria-describedby={error ? `${countId} ${errorId}` : countId}
    >
      <legend className="visually-hidden">Object classes</legend>
      <div className="class-toolbar">
        <div className="preset-buttons" role="group" aria-label="Class presets">
          <button
            type="button"
            className="button-secondary"
            aria-pressed={isVehiclePreset}
            onClick={() => emit(VEHICLE_CLASS_IDS)}
          >
            Vehicles (default)
          </button>
          <button type="button" className="button-secondary" onClick={() => emit(ALL_CLASS_IDS)}>
            All {COCO_CLASSES.length} classes
          </button>
          <button
            type="button"
            className="button-secondary"
            onClick={() => emit([])}
            disabled={selected.length === 0}
          >
            Clear
          </button>
        </div>
        <p id={countId} className="class-count" aria-live="polite">
          {selected.length} of {COCO_CLASSES.length} selected
        </p>
      </div>

      {selected.length > 0 && selected.length <= 12 && (
        <ul className="chip-list selected-chips" aria-label="Selected classes">
          {selected.map((id) => (
            <li key={id}>
              <button
                type="button"
                className="chip removable"
                onClick={() => toggle(id)}
                aria-label={`Remove ${className(id)}`}
              >
                {classLabel(className(id))} <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <label htmlFor={searchId} className="visually-hidden">
        Search object classes
      </label>
      <input
        id={searchId}
        type="search"
        className="text-input search-input"
        placeholder="Search classes (e.g. person, dog, traffic light)"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      <div className="class-grid" role="group" aria-label="COCO object classes">
        {visible.length === 0 ? (
          <p className="muted-text">No class matches “{query.trim()}”.</p>
        ) : (
          visible.map((item) => (
            <label key={item.id} className={`class-option ${chosen.has(item.id) ? "checked" : ""}`}>
              <input
                type="checkbox"
                checked={chosen.has(item.id)}
                onChange={() => toggle(item.id)}
              />
              <span>{classLabel(item.name)}</span>
              <span className="class-id" aria-hidden="true">
                {item.id}
              </span>
            </label>
          ))
        )}
      </div>
      {error && (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      )}
      <p className="field-hint">
        COCO classes of the pretrained YOLO detection models. Results count bounding-box
        detections per frame, not unique objects.
      </p>
    </fieldset>
  );
}
