package com.yolovision.dto;

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
}
