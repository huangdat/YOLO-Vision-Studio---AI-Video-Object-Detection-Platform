package com.yolovision.dto.messaging;

import com.yolovision.entity.ProcessingMode;
import com.yolovision.entity.InferencePrecision;
import com.yolovision.entity.InferenceRuntime;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Schema version 1 worker event. One shape covers progress, completion, and failure:
 * {@code result} is required for and only allowed on COMPLETED, {@code error} on FAILED.
 */
public record DetectionEventMessage(
        @NotNull Integer schemaVersion,
        @NotNull UUID eventId,
        @NotNull UUID jobId,
        @NotNull DetectionEventStatus status,
        @NotNull @Min(0) @Max(100) Integer progress,
        @PositiveOrZero Integer processedFrames,
        @PositiveOrZero Integer totalFrames,
        @Size(max = 500) String message,
        @NotNull Instant timestamp,
        @Pattern(regexp = "^[a-z0-9][a-z0-9_-]{0,63}$") String modelKey,
        @Valid Result result,
        @Valid Error error) {

    public record Result(
            @NotBlank @Size(max = 1024) String outputVideoKey,
            @NotBlank @Size(max = 1024) String resultJsonKey,
            @NotNull @PositiveOrZero Integer totalFrames,
            @NotNull @PositiveOrZero Long processingTimeMs,
            @NotNull Map<@NotBlank @Size(max = 128) String, @NotNull @PositiveOrZero Long> detectionSummary,
            ProcessingMode processingMode,
            @Valid Tracking tracking,
            InferencePrecision effectivePrecision,
            InferenceRuntime inferenceRuntime,
            @Pattern(regexp = "^(cpu|cuda:[0-9]{1,2})$") String inferenceDevice) {

        /** Completion of a detection-only job (no tracking fields), as sent by every worker version. */
        public Result(String outputVideoKey, String resultJsonKey, Integer totalFrames, Long processingTimeMs,
                Map<String, Long> detectionSummary) {
            this(outputVideoKey, resultJsonKey, totalFrames, processingTimeMs, detectionSummary, null, null);
        }

        /** Completion from a worker that does not report precision (before Phase 3). */
        public Result(String outputVideoKey, String resultJsonKey, Integer totalFrames, Long processingTimeMs,
                Map<String, Long> detectionSummary, ProcessingMode processingMode, Tracking tracking) {
            this(outputVideoKey, resultJsonKey, totalFrames, processingTimeMs, detectionSummary, processingMode,
                    tracking, null, null, null);
        }

        /** Completion from a worker that reports precision but not the device. */
        public Result(String outputVideoKey, String resultJsonKey, Integer totalFrames, Long processingTimeMs,
                Map<String, Long> detectionSummary, ProcessingMode processingMode, Tracking tracking,
                InferencePrecision effectivePrecision, InferenceRuntime inferenceRuntime) {
            this(outputVideoKey, resultJsonKey, totalFrames, processingTimeMs, detectionSummary, processingMode,
                    tracking, effectivePrecision, inferenceRuntime, null);
        }
    }

    /** Compact tracking totals of a DETECTION_TRACKING job; full per-track data is in result.json. */
    public record Tracking(
            @NotBlank @Pattern(regexp = "^bytetrack$") String tracker,
            @NotNull @PositiveOrZero Long uniqueTrackIds,
            @NotNull @PositiveOrZero Integer maxActiveTracks,
            @NotNull @PositiveOrZero Long trackedDetections,
            @NotNull Map<@NotBlank @Size(max = 128) String, @NotNull @PositiveOrZero Long> uniqueTrackIdsByClass) {
    }

    public record Error(
            @NotBlank @Pattern(regexp = "^[A-Z][A-Z0-9_]{0,63}$") String code,
            @NotBlank @Size(max = 1000) String message,
            Boolean retryable) {
    }
}
