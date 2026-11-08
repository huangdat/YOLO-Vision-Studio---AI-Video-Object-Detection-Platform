package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Result metadata of a COMPLETED job. Counts are bounding-box detections summed over all
 * processed frames (countSemantics), not unique objects. Storage locations are not exposed;
 * download and preview APIs belong to a later phase.
 */
public record DetectionResultMetadataResponse(
        UUID jobId,
        DetectionJobStatus status,
        String modelKey,
        String modelVersion,
        Integer totalFrames,
        long totalDetections,
        Long processingTimeMs,
        Map<String, Long> detectionSummary,
        String countSemantics,
        boolean outputVideoAvailable,
        boolean resultMetadataAvailable,
        Instant createdAt,
        Instant completedAt) {

    public static final String FRAME_DETECTIONS = "BOUNDING_BOX_DETECTIONS_ACROSS_FRAMES";

    public DetectionResultMetadataResponse {
        detectionSummary = Map.copyOf(detectionSummary);
    }
}
