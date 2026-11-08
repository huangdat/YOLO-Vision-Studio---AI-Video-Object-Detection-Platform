package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionSourceType;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Job state for clients. {@code videoUrl} is only populated for YouTube sources; local
 * development sources are never exposed. Error fields are the sanitized worker values.
 */
public record DetectionJobDetailsResponse(
        UUID jobId,
        String modelKey,
        String modelVersion,
        DetectionSourceType sourceType,
        String videoUrl,
        DetectionJobStatus status,
        int progress,
        BigDecimal confidence,
        int imageSize,
        List<Integer> classes,
        Instant createdAt,
        Instant startedAt,
        Instant completedAt,
        Instant updatedAt,
        String errorCode,
        String errorMessage) {

    public DetectionJobDetailsResponse {
        classes = List.copyOf(classes);
    }
}
