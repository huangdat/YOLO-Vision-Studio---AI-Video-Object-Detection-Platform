import { useId } from "react";
import { DEFAULT_IMAGE_SIZE, IMAGE_SIZES, parseConfidence } from "../../lib/detectionForm";

/** Slider and numeric field share one text value, so they always agree. */
export function ConfidenceControl({
  value,
  error,
  disabled,
  onChange,
}: {
  value: string;
  error?: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const sliderId = useId();
  const numberId = useId();
  const hintId = useId();
  const errorId = useId();
  const parsed = parseConfidence(value);
  const describedBy = error ? `${errorId} ${hintId}` : hintId;
  return (
    <div className="form-field">
      <label htmlFor={sliderId} className="field-label">
        Confidence threshold
      </label>
      <div className="range-row">
        <span className="range-bound" aria-hidden="true">0.00</span>
        <input
          id={sliderId}
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={parsed ?? 0.25}
          disabled={disabled}
          onChange={(event) => onChange(Number(event.target.value).toFixed(2))}
          aria-describedby={describedBy}
          aria-valuetext={parsed === null ? "invalid value" : parsed.toFixed(3)}
        />
        <span className="range-bound" aria-hidden="true">1.00</span>
        <label htmlFor={numberId} className="visually-hidden">
          Confidence threshold value
        </label>
        <input
          id={numberId}
          type="number"
          inputMode="decimal"
          min={0}
          max={1}
          step={0.001}
          className="text-input number-input"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
        />
      </div>
      {error && (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      )}
      <p id={hintId} className="field-hint">
        Detections below this confidence are discarded. Higher values reduce lower-confidence
        detections; this is not an accuracy score.
      </p>
    </div>
  );
}

export function ImageSizeSelector({
  value,
  disabled,
  onChange,
}: {
  value: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  const id = useId();
  const hintId = useId();
  return (
    <div className="form-field">
      <label htmlFor={id} className="field-label">
        Inference image size
      </label>
      <select
        id={id}
        className="select-input"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-describedby={hintId}
      >
        {IMAGE_SIZES.map((size) => (
          <option key={size} value={size}>
            {size} px{size === DEFAULT_IMAGE_SIZE ? " (default)" : ""}
          </option>
        ))}
      </select>
      <p id={hintId} className="field-hint">
        Higher image sizes may improve detail on small objects but increase processing time and
        resource usage, especially on CPU workers.
      </p>
    </div>
  );
}
