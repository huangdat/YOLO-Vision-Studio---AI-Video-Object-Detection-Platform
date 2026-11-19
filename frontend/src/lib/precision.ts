import type { InferencePrecision, InferenceRuntime } from "../types/detections";

/** Default for every new job; INT8 is opt-in and experimental. */
export const DEFAULT_PRECISION: InferencePrecision = "FP32";

/** Short label of a requested precision. */
export function precisionLabel(precision: InferencePrecision): string {
  return precision === "INT8" ? "INT8 · Optimized (experimental)" : "FP32 · Standard";
}

/** Requested precision of a job; `null` comes from backends without precision support. */
export function requestedPrecisionText(precision: InferencePrecision | null): string {
  return precision === null ? "Not recorded" : precision;
}

/**
 * What actually ran, strictly from the worker's result (never from the request): for example
 * "OpenVINO INT8" or "PyTorch FP32". `null` values mean the result predates precision reporting
 * or the job has not completed.
 */
export function executedPrecisionText(
  effective: InferencePrecision | null,
  runtime: InferenceRuntime | null,
  inferenceDevice: string | null = null,
): string | null {
  if (effective === null) return null;
  const engine = runtime === "OPENVINO" ? "OpenVINO" : runtime === "PYTORCH" ? "PyTorch" : null;
  const text = engine ? `${engine} ${effective}` : effective;
  const where = deviceLabel(inferenceDevice);
  return where ? `${text} · ${where}` : text;
}

/** "GPU (cuda:0)" or "CPU"; null when the device was not reported. */
export function deviceLabel(inferenceDevice: string | null): string | null {
  if (!inferenceDevice) return null;
  return inferenceDevice.startsWith("cuda") ? `GPU (${inferenceDevice})` : "CPU";
}

/** Extra guidance for failures caused by the precision setting; null for other errors. */
export function precisionErrorHint(errorCode: string | null | undefined): string | null {
  if (errorCode === "INT8_MODEL_UNAVAILABLE") {
    return "This model has no usable INT8 version on the worker. An operator can export one with " +
      "'python -m app.cli models quantize', or you can start the job again with FP32.";
  }
  if (errorCode === "PRECISION_MISMATCH") {
    return "The worker ran a different precision than requested, so the result was not stored. " +
      "Start the job again; if it repeats, check the worker's precision configuration.";
  }
  return null;
}
