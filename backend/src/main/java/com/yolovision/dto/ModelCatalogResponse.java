package com.yolovision.dto;

import java.util.List;

/** Registered model metadata; {@code enabled} is administrative, not worker readiness. */
public record ModelCatalogResponse(List<ModelConfigResponse> models, int total) {

    public ModelCatalogResponse {
        models = List.copyOf(models);
    }

    public static ModelCatalogResponse of(List<ModelConfigResponse> models) {
        return new ModelCatalogResponse(models, models.size());
    }
}
