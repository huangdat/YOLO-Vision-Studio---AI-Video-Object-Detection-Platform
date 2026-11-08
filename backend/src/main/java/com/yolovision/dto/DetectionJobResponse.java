package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public record DetectionJobResponse(
        UUID id,
        UUID modelId,
        String videoUrl,
        BigDecimal confidence,
        Integer imageSize,
        List<Integer> selectedClasses,
        DetectionJobStatus status,
        int progress,
        String errorMessage,
        Instant createdAt,
        Instant startedAt,
        Instant completedAt,
        Instant updatedAt) {

    public DetectionJobResponse {
        selectedClasses = List.copyOf(selectedClasses);
    }
}
