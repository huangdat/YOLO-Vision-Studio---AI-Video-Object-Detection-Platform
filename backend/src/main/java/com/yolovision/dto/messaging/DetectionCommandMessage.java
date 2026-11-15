package com.yolovision.dto.messaging;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.yolovision.entity.DetectionSourceType;
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
        @JsonInclude(JsonInclude.Include.NON_NULL) ProcessingMode processingMode) {

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
                createdAt, null);
    }
}
