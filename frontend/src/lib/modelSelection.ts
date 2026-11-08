import type { ModelConfig } from "../types/models";
import { MODEL_SIZES } from "./format";

/**
 * Model choice for the workspace. The catalog is authoritative: a version and size
 * select a model only when a matching record exists; keys are never constructed.
 */
export interface ModelChoice {
  version: string;
  size: string;
}

const sizeOrder = (size: string) => {
  const index = MODEL_SIZES.indexOf(size);
  return index === -1 ? MODEL_SIZES.length : index;
};

/** Versions in the backend's release order, limited to those with registered models. */
export function availableVersions(models: ModelConfig[], versionOrder: string[]): string[] {
  const present = new Set(models.map((model) => model.version));
  const ordered = versionOrder.filter((version) => present.has(version));
  const extra = [...present].filter((version) => !versionOrder.includes(version)).sort();
  return [...ordered, ...extra];
}

/** Registered models of one version, smallest size first. */
export function modelsForVersion(models: ModelConfig[], version: string): ModelConfig[] {
  return models
    .filter((model) => model.version === version)
    .sort((a, b) => sizeOrder(a.modelSize) - sizeOrder(b.modelSize));
}

export function resolveModel(models: ModelConfig[], choice: ModelChoice | null): ModelConfig | undefined {
  if (!choice) return undefined;
  return models.find((model) => model.version === choice.version && model.modelSize === choice.size);
}

/** The first enabled model in release and size order; otherwise the first registered model. */
export function defaultChoice(models: ModelConfig[], versionOrder: string[]): ModelChoice | null {
  const ordered = availableVersions(models, versionOrder).flatMap((version) =>
    modelsForVersion(models, version),
  );
  const preferred = ordered.find((model) => model.enabled) ?? ordered[0];
  return preferred ? { version: preferred.version, size: preferred.modelSize } : null;
}

/**
 * Choice after the version changes: keep the size when that model exists, otherwise
 * prefer an enabled size of the new version, otherwise its smallest size.
 */
export function choiceForVersion(
  models: ModelConfig[],
  version: string,
  previousSize: string | undefined,
): ModelChoice | null {
  const candidates = modelsForVersion(models, version);
  if (candidates.length === 0) return null;
  const kept = candidates.find((model) => model.modelSize === previousSize);
  const next = kept ?? candidates.find((model) => model.enabled) ?? candidates[0];
  return { version, size: next.modelSize };
}

/** Keeps a still-valid choice after the catalog reloads; otherwise falls back to the default. */
export function reconcileChoice(
  models: ModelConfig[],
  versionOrder: string[],
  current: ModelChoice | null,
): ModelChoice | null {
  return resolveModel(models, current) ? current : defaultChoice(models, versionOrder);
}
