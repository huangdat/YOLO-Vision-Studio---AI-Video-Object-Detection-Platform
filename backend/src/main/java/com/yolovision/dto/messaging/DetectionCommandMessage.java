package com.yolovision.dto.messaging;

import com.yolovision.entity.DetectionSourceType;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Schema version 1 detection command, serialised as camelCase JSON. Contains no
 * credentials, filesystem paths, or checkpoint locations: the worker resolves
 * {@code modelKey} through its own allowlist. Mirrored by the worker's
 * {@code app/schemas/messaging.py}.
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
        Instant createdAt) {

    public static final int SCHEMA_VERSION = 1;
    public static final String MESSAGE_TYPE = "detection.execute.v1";

    public DetectionCommandMessage {
        classes = List.copyOf(classes);
    }
}
