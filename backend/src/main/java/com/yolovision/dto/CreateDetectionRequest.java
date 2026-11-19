package com.yolovision.dto;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import io.swagger.v3.oas.annotations.media.Schema;
import java.math.BigDecimal;
import java.util.List;

/**
 * Public job submission body. Only YouTube video URLs are accepted; unknown fields such as
 * {@code sourceType} or {@code source} are rejected, so clients cannot submit local paths.
 * All rules are enforced by DetectionJobSubmissionService (one validation system).
 */
@Schema(description = "Detection job submission")
public record CreateDetectionRequest(
        @Schema(description = "Single YouTube video URL (watch, youtu.be, shorts, or embed form; no playlists)",
                example = "https://www.youtube.com/watch?v=VIDEO_ID_11", requiredMode = Schema.RequiredMode.REQUIRED)
        String videoUrl,
        @Schema(description = "Enabled detection model key from GET /api/v1/models", example = "yolo11n",
                requiredMode = Schema.RequiredMode.REQUIRED)
        String modelKey,
        @Schema(description = "Confidence threshold 0-1 with at most 3 decimals; default 0.25", example = "0.25")
        BigDecimal confidence,
        @Schema(description = "Inference image size: 32-4096 and a multiple of 32; default 960", example = "640")
        Integer imageSize,
        @Schema(description = "1-100 unique class ids of the model; default COCO vehicles [1,2,3,5,7]",
                example = "[1, 2, 3, 5, 7]")
        List<Integer> classes,
        @Schema(description = "DETECTION_ONLY (default) or DETECTION_TRACKING (adds ByteTrack Track IDs)",
                example = "DETECTION_TRACKING", allowableValues = {"DETECTION_ONLY", "DETECTION_TRACKING"})
        String processingMode,
        @Schema(description = "FP32 (default, PyTorch) or INT8 (experimental OpenVINO INT8, CPU only; needs an "
                + "exported INT8 model on the worker, otherwise the job fails with INT8_MODEL_UNAVAILABLE). "
                + "Case-insensitive.", example = "FP32", allowableValues = {"FP32", "INT8"})
        String inferencePrecision) {

    /** Requests written before tracking existed (no processingMode) mean Detection Only. */
    public CreateDetectionRequest(String videoUrl, String modelKey, BigDecimal confidence, Integer imageSize,
            List<Integer> classes) {
        this(videoUrl, modelKey, confidence, imageSize, classes, null, null);
    }

    /** Requests written before precision existed (no inferencePrecision) mean FP32. */
    public CreateDetectionRequest(String videoUrl, String modelKey, BigDecimal confidence, Integer imageSize,
            List<Integer> classes, String processingMode) {
        this(videoUrl, modelKey, confidence, imageSize, classes, processingMode, null);
    }

    /**
     * Spring Boot's mapper ignores unknown properties globally; this public contract rejects
     * them instead (parsing fails with 400 MALFORMED_REQUEST), without changing other DTOs.
     */
    @JsonAnySetter
    void rejectUnknownProperty(String name, Object value) {
        throw new IllegalArgumentException("Unsupported property");
    }
}
