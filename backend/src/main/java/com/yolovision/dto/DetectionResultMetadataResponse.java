package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.InferencePrecision;
import com.yolovision.entity.InferenceRuntime;
import com.yolovision.entity.ProcessingMode;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Result metadata of a COMPLETED job. Counts are bounding-box detections summed over all
 * processed frames (countSemantics), not unique objects. Storage locations are not exposed;
 * the artifacts themselves are served by DetectionArtifactController (Phase 09).
 * {@code effectivePrecision} and {@code inferenceRuntime} are what the worker actually ran; both are
 * null for results stored before workers reported them.
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
        Instant completedAt,
        ProcessingMode processingMode,
        Tracking tracking,
        InferencePrecision effectivePrecision,
        InferenceRuntime inferenceRuntime) {

    public static final String FRAME_DETECTIONS = "BOUNDING_BOX_DETECTIONS_ACROSS_FRAMES";
    public static final String TRACK_IDS = "TRACK_IDS_ASSIGNED_BY_BYTETRACK";

    public DetectionResultMetadataResponse {
        detectionSummary = Map.copyOf(detectionSummary);
    }

    public DetectionResultMetadataResponse(UUID jobId, DetectionJobStatus status, String modelKey,
            String modelVersion, Integer totalFrames, long totalDetections, Long processingTimeMs,
            Map<String, Long> detectionSummary, String countSemantics, boolean outputVideoAvailable,
            boolean resultMetadataAvailable, Instant createdAt, Instant completedAt, ProcessingMode processingMode,
            Tracking tracking) {
        this(jobId, status, modelKey, modelVersion, totalFrames, totalDetections, processingTimeMs, detectionSummary,
                countSemantics, outputVideoAvailable, resultMetadataAvailable, createdAt, completedAt, processingMode,
                tracking, null, null);
    }

    /**
     * Tracking totals; null in Detection Only mode and for results stored without them.
     * {@code uniqueTrackIds} counts IDs ByteTrack assigned within this job (countSemantics);
     * occlusion and ID switches mean it can differ from the number of physical objects.
     */
    public record Tracking(
            String tracker,
            long uniqueTrackIds,
            int maxActiveTracks,
            long trackedDetections,
            Map<String, Long> uniqueTrackIdsByClass,
            String countSemantics) {

        public Tracking {
            uniqueTrackIdsByClass = Map.copyOf(uniqueTrackIdsByClass);
        }
    }
}
