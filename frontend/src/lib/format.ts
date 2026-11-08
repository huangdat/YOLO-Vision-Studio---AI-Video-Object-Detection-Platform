/** Display helpers. Nullable or unparsable values render as an em dash, never "Invalid Date". */

const EMPTY = "—";

const dateTime = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? EMPTY : dateTime.format(date);
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? EMPTY : value.toLocaleString();
}

/** 10833 -> "10.8 s", 125000 -> "2 min 5 s". */
export function formatDuration(milliseconds: number | null | undefined): string {
  if (milliseconds === null || milliseconds === undefined || milliseconds < 0) return EMPTY;
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  const seconds = milliseconds / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
}

/** First 8 characters of a UUID for compact tables; the full id stays available. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}

const SIZE_NAMES: Record<string, string> = {
  n: "Nano",
  s: "Small",
  m: "Medium",
  l: "Large",
  x: "Extra Large",
};

export const MODEL_SIZES = Object.keys(SIZE_NAMES);

export function sizeName(size: string): string {
  return SIZE_NAMES[size] ?? size;
}

/** "bus" -> "Bus", "traffic light" -> "Traffic light". */
export function classLabel(name: string): string {
  return name ? name.charAt(0).toUpperCase() + name.slice(1) : name;
}
