import { useId, useState } from "react";
import {
  ALL_CLASS_IDS,
  COCO_CLASSES,
  className,
  VEHICLE_CLASS_IDS,
} from "../../lib/cocoClasses";
import { classLabel } from "../../lib/format";

type Preset = "vehicles" | "all" | "custom";

const sameSet = (selected: number[], ids: readonly number[]) =>
  selected.length === ids.length && ids.every((id) => selected.includes(id));

/**
 * COCO class picker. Two presets cover the common cases; "Custom" opens a searchable list
 * of all 80 classes. Emits sorted, duplicate-free IDs.
 */
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
  const [customChosen, setCustomChosen] = useState(false);
  const [query, setQuery] = useState("");
  const groupName = useId();
  const searchId = useId();
  const countId = useId();
  const errorId = useId();
  const chosen = new Set(selected);
  const preset: Preset = customChosen
    ? "custom"
    : sameSet(selected, VEHICLE_CLASS_IDS)
      ? "vehicles"
      : sameSet(selected, ALL_CLASS_IDS)
        ? "all"
        : "custom";
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
  const choose = (next: Preset) => {
    setCustomChosen(next === "custom");
    if (next === "vehicles") emit(VEHICLE_CLASS_IDS);
    if (next === "all") emit(ALL_CLASS_IDS);
  };

  const options: { value: Preset; title: string; description: string }[] = [
    {
      value: "vehicles",
      title: "Vehicles",
      description: VEHICLE_CLASS_IDS.map((id) => classLabel(className(id))).join(", "),
    },
    { value: "all", title: "All objects", description: `All ${COCO_CLASSES.length} COCO classes` },
    { value: "custom", title: "Custom", description: "Pick specific classes" },
  ];

  return (
    <fieldset
      className="form-field class-selector"
      disabled={disabled}
      aria-describedby={error ? `${countId} ${errorId}` : countId}
    >
      <legend className="field-label">Objects to detect</legend>
      <div className="choice-cards" role="radiogroup" aria-label="Class presets">
        {options.map((option) => (
          <label key={option.value} className={`choice-card ${preset === option.value ? "checked" : ""}`}>
            <input
              type="radio"
              name={groupName}
              value={option.value}
              checked={preset === option.value}
              onChange={() => choose(option.value)}
            />
            <span className="choice-title">{option.title}</span>
            <span className="choice-description">{option.description}</span>
          </label>
        ))}
      </div>

      <p id={countId} className="class-count" aria-live="polite">
        {selected.length} of {COCO_CLASSES.length} selected
      </p>

      {preset === "custom" && (
        <div className="custom-classes">
          {selected.length > 0 && selected.length <= 12 && (
            <ul className="chip-list" aria-label="Selected classes">
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
          <div className="custom-toolbar">
            <label htmlFor={searchId} className="visually-hidden">
              Search object classes
            </label>
            <input
              id={searchId}
              type="search"
              className="text-input"
              placeholder="Search classes, e.g. person, dog, traffic light"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <button
              type="button"
              className="button-ghost"
              onClick={() => emit([])}
              disabled={selected.length === 0}
            >
              Clear selection
            </button>
          </div>
          <div className="class-grid" role="group" aria-label="COCO object classes">
            {visible.length === 0 ? (
              <p className="muted-text">No class matches “{query.trim()}”.</p>
            ) : (
              visible.map((item) => (
                <label key={item.id} className={`class-option ${chosen.has(item.id) ? "checked" : ""}`}>
                  <input type="checkbox" checked={chosen.has(item.id)} onChange={() => toggle(item.id)} />
                  <span>{classLabel(item.name)}</span>
                </label>
              ))
            )}
          </div>
        </div>
      )}
      {error && (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      )}
      <p className="field-hint">
        Results count detections in every frame, not unique objects.
      </p>
    </fieldset>
  );
}
