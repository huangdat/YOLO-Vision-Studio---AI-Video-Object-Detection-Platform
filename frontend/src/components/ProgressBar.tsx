import type { StatusTone } from "../lib/jobStatus";

export function ProgressBar({
  value,
  label,
  tone = "purple",
  size = "regular",
}: {
  value: number;
  label: string;
  tone?: StatusTone;
  size?: "regular" | "small";
}) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div
      className={`progress-track ${size}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
    >
      <span className={`progress-fill tone-${tone}`} style={{ width: `${clamped}%` }} />
    </div>
  );
}
