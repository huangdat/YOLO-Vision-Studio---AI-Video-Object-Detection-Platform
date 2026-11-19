package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.InferencePrecision;
import com.yolovision.entity.ProcessingMode;
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
        String errorCode,
        ProcessingMode processingMode,
        InferencePrecision inferencePrecision) {

    public DetectionJobSummaryResponse(UUID jobId, String modelKey, DetectionJobStatus status, int progress,
            Instant createdAt, Instant completedAt, String errorCode, ProcessingMode processingMode) {
        this(jobId, modelKey, status, progress, createdAt, completedAt, errorCode, processingMode,
                InferencePrecision.FP32);
    }
}
