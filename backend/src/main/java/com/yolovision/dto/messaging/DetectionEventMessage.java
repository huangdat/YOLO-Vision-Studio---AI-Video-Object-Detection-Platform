package com.yolovision.dto.messaging;

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
            @NotNull Map<@NotBlank @Size(max = 128) String, @NotNull @PositiveOrZero Long> detectionSummary) {
    }

    public record Error(
            @NotBlank @Pattern(regexp = "^[A-Z][A-Z0-9_]{0,63}$") String code,
            @NotBlank @Size(max = 1000) String message,
            Boolean retryable) {
    }
}
