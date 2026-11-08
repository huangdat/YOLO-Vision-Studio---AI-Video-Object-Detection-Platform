package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import java.time.Instant;
import java.util.UUID;

/** One row of the job history. */
public record DetectionJobSummaryResponse(
        UUID jobId,
        String modelKey,
        DetectionJobStatus status,
        int progress,
        Instant createdAt,
        Instant completedAt,
        String errorCode) {
}
