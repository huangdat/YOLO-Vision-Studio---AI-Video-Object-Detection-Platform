import { apiClient, request } from "./client";
import { array, boolean, invalid, record, string, type JsonRecord } from "./guards";
import type {
  ModelCatalogFilter,
  ModelCatalogResponse,
  ModelConfig,
  ModelVersionsResponse,
} from "../types/models";

function toModel(value: unknown): ModelConfig {
  const data: JsonRecord = record(value);
  return {
    id: string(data, "id"),
    modelKey: string(data, "modelKey"),
    version: string(data, "version"),
    modelSize: string(data, "modelSize"),
    taskType: string(data, "taskType"),
    weightsFilename: string(data, "weightsFilename"),
    enabled: boolean(data, "enabled"),
    createdAt: string(data, "createdAt"),
    updatedAt: string(data, "updatedAt"),
  };
}

/** GET /models with optional server-side filters. */
export function listModels(
  filter: ModelCatalogFilter = {},
  signal?: AbortSignal,
): Promise<ModelCatalogResponse> {
  return request(async () => {
    const params: Record<string, string> = {};
    if (filter.version) params.version = filter.version;
    if (filter.size) params.size = filter.size;
    if (filter.enabled !== undefined) params.enabled = String(filter.enabled);
    const { data } = await apiClient.get<unknown>("/models", { params, signal });
    const body = record(data);
    const models = array(body.models).map(toModel);
    return { models, total: typeof body.total === "number" ? body.total : models.length };
  });
}

/** GET /models/versions: registered YOLO families in release order. */
export function getModelVersions(signal?: AbortSignal): Promise<ModelVersionsResponse> {
  return request(async () => {
    const { data } = await apiClient.get<unknown>("/models/versions", { signal });
    const versions = array(record(data).versions).map((value) => {
      if (typeof value !== "string") invalid();
      return value;
    });
    return { versions };
  });
}

/** GET /models/{modelKey}. */
export function getModel(modelKey: string, signal?: AbortSignal): Promise<ModelConfig> {
  return request(async () => {
    const { data } = await apiClient.get<unknown>(
      `/models/${encodeURIComponent(modelKey)}`,
      { signal },
    );
    return toModel(data);
  });
}
