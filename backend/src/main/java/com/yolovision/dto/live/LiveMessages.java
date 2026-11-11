package com.yolovision.dto.live;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * Live Detection WebSocket protocol, version 1 (see docs/live-detection-architecture.md).
 * Text frames carry these JSON messages; binary frames carry camera images as
 * {@code [uint32 big-endian frameId][JPEG bytes]}.
 */
public final class LiveMessages {

    public static final int PROTOCOL_VERSION = 1;

    private LiveMessages() {
    }

    // Client -> server --------------------------------------------------------------------

    /** {"type":"start","version":1,"modelKey":"yolo11n","confidence":0.25,"imageSize":416,"classes":[...]} */
    @JsonIgnoreProperties(ignoreUnknown = false)
    public record StartRequest(String type, Integer version, String modelKey, BigDecimal confidence,
            Integer imageSize, List<Integer> classes) {
    }

    // Server -> client --------------------------------------------------------------------

    public record Ready(String type, int version, String sessionId, String modelKey, int maxFps,
            int maxFrameBytes, int maxInFlight, int imageSize, BigDecimal confidence, List<Integer> classes) {

        public Ready(String sessionId, String modelKey, int maxFps, int maxFrameBytes, int imageSize,
                BigDecimal confidence, List<Integer> classes) {
            this("ready", PROTOCOL_VERSION, sessionId, modelKey, maxFps, maxFrameBytes, 1, imageSize, confidence,
                    classes);
        }
    }

    /** Box coordinates are pixels of the submitted frame: [x1, y1, x2, y2]. */
    public record Detection(int classId, String label, double confidence, List<Double> box) {
    }

    public record Detections(String type, long frameId, int width, int height, List<Detection> detections,
            double inferenceMs, long serverMs) {

        public Detections(long frameId, int width, int height, List<Detection> detections, double inferenceMs,
                long serverMs) {
            this("detections", frameId, width, height, detections, inferenceMs, serverMs);
        }
    }

    public record Dropped(String type, long frameId, String reason) {

        public static Dropped busy(long frameId) {
            return new Dropped("dropped", frameId, "BUSY");
        }

        public static Dropped rateLimited(long frameId) {
            return new Dropped("dropped", frameId, "RATE_LIMITED");
        }
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Error(String type, String code, String message, boolean fatal, Long frameId,
            Map<String, String> errors) {

        public static Error of(String code, String message, boolean fatal) {
            return new Error("error", code, message, fatal, null, null);
        }

        public static Error forFrame(long frameId, String code, String message) {
            return new Error("error", code, message, false, frameId, null);
        }

        public static Error invalidSettings(Map<String, String> errors) {
            return new Error("error", "INVALID_SETTINGS", "The live detection settings are invalid.", true, null,
                    errors);
        }
    }

    public record Stopped(String type, String reason, long processedFrames, long droppedFrames) {

        public Stopped(String reason, long processedFrames, long droppedFrames) {
            this("stopped", reason, processedFrames, droppedFrames);
        }
    }

    // Internal worker contract --------------------------------------------------------------

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record WorkerResult(long frameId, String modelKey, int width, int height, List<Detection> detections,
            double inferenceMs) {
    }
}
