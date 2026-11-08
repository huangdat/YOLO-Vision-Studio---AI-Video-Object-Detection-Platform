/** ModelConfigResponse. `enabled` is administrative only, not worker readiness. */
export interface ModelConfig {
  id: string;
  modelKey: string;
  version: string;
  modelSize: string;
  taskType: string;
  weightsFilename: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ModelCatalogResponse {
  models: ModelConfig[];
  total: number;
}

export interface ModelVersionsResponse {
  versions: string[];
}

export interface ModelCatalogFilter {
  version?: string;
  size?: string;
  enabled?: boolean;
}
