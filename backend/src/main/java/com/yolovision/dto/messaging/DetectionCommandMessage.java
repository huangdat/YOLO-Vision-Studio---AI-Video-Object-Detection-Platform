package com.yolovision.dto.messaging;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.yolovision.entity.DetectionSourceType;
import com.yolovision.entity.InferencePrecision;
import com.yolovision.entity.ProcessingMode;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Schema version 1 detection command, serialised as camelCase JSON. Contains no
 * credentials, filesystem paths, or checkpoint locations: the worker resolves
 * {@code modelKey} through its own allowlist. Mirrored by the worker's
 * {@code app/schemas/messaging.py}.
 *
 * <p>{@code processingMode} is optional and additive: it is sent only for tracking jobs, so
 * detection-only commands are byte-for-byte what they were before tracking existed.
 *
 * <p>{@code inferencePrecision} is sent for every job created by this version (FP32 or INT8), so
 * the worker runs exactly the requested precision. It requires a worker that knows the field
 * (deploy the worker first). A command without it keeps the worker's configured default.
 */
public record DetectionCommandMessage(
        int schemaVersion,
        UUID messageId,
        UUID jobId,
        String modelKey,
        DetectionSourceType sourceType,
        String source,
        BigDecimal confidence,
        int imageSize,
        List<Integer> classes,
        Instant createdAt,
        @JsonInclude(JsonInclude.Include.NON_NULL) ProcessingMode processingMode,
        @JsonInclude(JsonInclude.Include.NON_NULL) InferencePrecision inferencePrecision) {

    public static final int SCHEMA_VERSION = 1;
    public static final String MESSAGE_TYPE = "detection.execute.v1";

    public DetectionCommandMessage {
        classes = List.copyOf(classes);
        processingMode = processingMode == ProcessingMode.DETECTION_ONLY ? null : processingMode;
    }

    public DetectionCommandMessage(int schemaVersion, UUID messageId, UUID jobId, String modelKey,
            DetectionSourceType sourceType, String source, BigDecimal confidence, int imageSize,
            List<Integer> classes, Instant createdAt) {
        this(schemaVersion, messageId, jobId, modelKey, sourceType, source, confidence, imageSize, classes,
                createdAt, null, null);
    }

    public DetectionCommandMessage(int schemaVersion, UUID messageId, UUID jobId, String modelKey,
            DetectionSourceType sourceType, String source, BigDecimal confidence, int imageSize,
            List<Integer> classes, Instant createdAt, ProcessingMode processingMode) {
        this(schemaVersion, messageId, jobId, modelKey, sourceType, source, confidence, imageSize, classes,
                createdAt, processingMode, null);
    }
}
