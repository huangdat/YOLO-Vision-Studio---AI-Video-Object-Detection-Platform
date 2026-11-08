package com.yolovision.dto;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

public record DetectionResultResponse(
        UUID id,
        UUID jobId,
        String inputVideoKey,
        String outputVideoKey,
        Integer totalFrames,
        Long processingTimeMs,
        Map<String, Long> detectionSummary,
        Instant createdAt) {

    public DetectionResultResponse {
        detectionSummary = Map.copyOf(detectionSummary);
    }
}
