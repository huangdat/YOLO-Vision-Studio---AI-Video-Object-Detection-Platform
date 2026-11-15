package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.InferencePrecision;
import com.yolovision.entity.DetectionSourceType;
import com.yolovision.entity.ProcessingMode;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Job state for clients. {@code videoUrl} is only populated for YouTube sources; local
 * development sources are never exposed. Error fields are the sanitized worker values.
 * {@code inferencePrecision} is the requested precision; what actually ran is reported in the
 * result metadata ({@code effectivePrecision}, {@code inferenceRuntime}).
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
        String errorMessage,
        ProcessingMode processingMode,
        InferencePrecision inferencePrecision) {
    public DetectionJobDetailsResponse {
        classes = List.copyOf(classes);
    }

    public DetectionJobDetailsResponse(UUID jobId, String modelKey, String modelVersion,
            DetectionSourceType sourceType, String videoUrl, DetectionJobStatus status, int progress,
            BigDecimal confidence, int imageSize, List<Integer> classes, Instant createdAt, Instant startedAt,
            Instant completedAt, Instant updatedAt, String errorCode, String errorMessage,
            ProcessingMode processingMode) {
        this(jobId, modelKey, modelVersion, sourceType, videoUrl, status, progress, confidence, imageSize, classes,
                createdAt, startedAt, completedAt, updatedAt, errorCode, errorMessage, processingMode,
                InferencePrecision.FP32);
    }
}
