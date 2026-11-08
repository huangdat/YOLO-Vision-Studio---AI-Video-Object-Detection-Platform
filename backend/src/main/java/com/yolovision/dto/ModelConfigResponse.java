package com.yolovision.dto;

import com.yolovision.entity.ModelConfig;
import java.time.Instant;
import java.util.UUID;

public record ModelConfigResponse(
        UUID id,
        String modelKey,
        String version,
        String modelSize,
        String taskType,
        String weightsFilename,
        boolean enabled,
        Instant createdAt,
        Instant updatedAt) {

    public static ModelConfigResponse from(ModelConfig model) {
        return new ModelConfigResponse(model.getId(), model.getModelKey(), model.getVersion(),
                model.getModelSize(), model.getTaskType(), model.getWeightsFilename(), model.isEnabled(),
                model.getCreatedAt(), model.getUpdatedAt());
    }
}
