import { useId } from "react";

/**
 * Opt-in ByteTrack tracking. Off means Detection Only (each frame analysed independently), which
 * is also how every job created before tracking existed was processed.
 */
export function TrackingToggle({
  checked,
  disabled,
  onChange,
  description = "Assign persistent IDs to detected objects across video frames.",
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  description?: string;
}) {
  const id = useId();
  return (
    <div className={`tracking-toggle ${checked ? "is-on" : ""}`}>
      <input
        id={id}
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        aria-describedby={`${id}-hint`}
        onChange={(event) => onChange(event.target.checked)}
      />
      <div>
        <label htmlFor={id} className="tracking-toggle-label">
          Object tracking <span className="tracking-toggle-tag">ByteTrack</span>
        </label>
        <p id={`${id}-hint`} className="field-hint">
          {description}
        </p>
      </div>
    </div>
  );
}

/** Short user-facing name of a processing mode. */
export function processingModeLabel(mode: "DETECTION_ONLY" | "DETECTION_TRACKING"): string {
  return mode === "DETECTION_TRACKING" ? "Detection + Tracking (ByteTrack)" : "Detection only";
}
