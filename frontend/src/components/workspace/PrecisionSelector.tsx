import { useId } from "react";
import type { InferencePrecision } from "../../types/detections";

const OPTIONS: { value: InferencePrecision; title: string; detail: string }[] = [
  { value: "FP32", title: "FP32 · Standard", detail: "Default. Full-precision PyTorch model." },
  { value: "INT8", title: "INT8 · Optimized", detail: "OpenVINO INT8 on the worker's CPU." },
];

/**
 * Per-job inference precision. FP32 is the default; INT8 is opt-in and experimental. The worker
 * runs exactly the selected precision: if the model has no INT8 version there, the job fails with
 * a clear error instead of silently running FP32.
 */
export function PrecisionSelector({
  value,
  disabled,
  onChange,
}: {
  value: InferencePrecision;
  disabled?: boolean;
  onChange: (value: InferencePrecision) => void;
}) {
  const id = useId();
  return (
    <fieldset className="precision-selector" aria-describedby={`${id}-hint`}>
      <legend className="precision-legend">Inference precision</legend>
      <div className="precision-options" role="radiogroup">
        {OPTIONS.map((option) => (
          <label key={option.value} className={`precision-option ${value === option.value ? "is-selected" : ""}`}>
            <input
              type="radio"
              name={`${id}-precision`}
              value={option.value}
              checked={value === option.value}
              disabled={disabled}
              onChange={() => onChange(option.value)}
            />
            <span>
              <span className="precision-option-title">
                {option.title}
                {option.value === "INT8" && <span className="precision-tag">Experimental</span>}
              </span>
              <span className="precision-option-detail">{option.detail}</span>
            </span>
          </label>
        ))}
      </div>
      <p id={`${id}-hint`} className="field-hint">
        {value === "INT8"
          ? "INT8 is usually about twice as fast on CPU, but detections and Track IDs can differ slightly " +
            "from FP32. It needs an INT8 version of the model exported on the worker; without one the job " +
            "fails with an explanation. Accuracy is validated for pedestrians (yolo11n), not yet for vehicles."
          : "Standard precision, the same as every earlier job."}
      </p>
    </fieldset>
  );
}
