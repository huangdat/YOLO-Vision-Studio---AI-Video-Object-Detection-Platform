package com.yolovision.dto.live;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.yolovision.entity.ProcessingMode;
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

    /**
     * {"type":"start","version":1,"modelKey":"yolo11n","confidence":0.25,"imageSize":416,"classes":[...],
     * "tracking":true,"trackingMode":"CLIENT"}. {@code tracking} is optional; absent or false means
     * Detection Only. {@code trackingMode} is optional: SERVER (the default, ByteTrack in the live worker)
     * or CLIENT (the worker only detects, at ByteTrack's low-score floor; the browser tracks).
     */
    @JsonIgnoreProperties(ignoreUnknown = false)
    public record StartRequest(String type, Integer version, String modelKey, BigDecimal confidence,
            Integer imageSize, List<Integer> classes, Boolean tracking, String trackingMode) {

        public StartRequest(String type, Integer version, String modelKey, BigDecimal confidence, Integer imageSize,
                List<Integer> classes, Boolean tracking) {
            this(type, version, modelKey, confidence, imageSize, classes, tracking, null);
        }
    }

    public static final String TRACKING_SERVER = "SERVER";
    public static final String TRACKING_CLIENT = "CLIENT";

    // Server -> client --------------------------------------------------------------------

    /**
     * {@code tracker} is "bytetrack" when tracking is enabled for the session, otherwise omitted.
     * {@code trackingMode} (SERVER or CLIENT) says where ByteTrack runs; omitted without tracking.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Ready(String type, int version, String sessionId, String modelKey, int maxFps,
            int maxFrameBytes, int maxInFlight, int imageSize, BigDecimal confidence, List<Integer> classes,
            boolean tracking, String tracker, String trackingMode) {
        public Ready(String sessionId, String modelKey, int maxFps, int maxFrameBytes, int imageSize,
                BigDecimal confidence, List<Integer> classes, boolean tracking) {
            this(sessionId, modelKey, maxFps, maxFrameBytes, imageSize, confidence, classes,
                    tracking ? TRACKING_SERVER : null);
        }

        public Ready(String sessionId, String modelKey, int maxFps, int maxFrameBytes, int imageSize,
                BigDecimal confidence, List<Integer> classes, String trackingMode) {
            this("ready", PROTOCOL_VERSION, sessionId, modelKey, maxFps, maxFrameBytes, 1, imageSize, confidence,
                    classes, trackingMode != null, trackingMode != null ? ProcessingMode.TRACKER : null, trackingMode);
        }
    }

    /**
     * Box coordinates are pixels of the submitted frame: [x1, y1, x2, y2]. {@code trackId} is the
     * worker's ByteTrack ID, present only in tracking sessions and only for confirmed tracks; it
     * is scoped to the session.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Detection(int classId, String label, double confidence, List<Double> box, Long trackId) {

        public Detection(int classId, String label, double confidence, List<Double> box) {
            this(classId, label, confidence, box, null);
        }
    }

    /**
     * {@code tracking} and {@code activeTracks} are sent only in server-tracking sessions. In CLIENT
     * tracking sessions {@code trackingMode} is "CLIENT", the detections carry no Track IDs, and
     * {@code lowScoreFloor} is the confidence YOLO ran at (boxes below the session confidence are
     * included for ByteTrack's second association). {@code device} and {@code precision} are what the
     * worker actually ran, when it reports them.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Detections(String type, long frameId, int width, int height, List<Detection> detections,
            double inferenceMs, long serverMs, Boolean tracking, Integer activeTracks, String trackingMode,
            Double lowScoreFloor, String device, String precision) {
        public Detections(long frameId, int width, int height, List<Detection> detections, double inferenceMs,
                long serverMs) {
            this("detections", frameId, width, height, detections, inferenceMs, serverMs, null, null, null, null,
                    null, null);
        }

        public Detections(long frameId, int width, int height, List<Detection> detections, double inferenceMs,
                long serverMs, Integer activeTracks) {
            this("detections", frameId, width, height, detections, inferenceMs, serverMs,
                    activeTracks == null ? null : Boolean.TRUE, activeTracks, null, null, null, null);
        }

        /** Same message with the worker's execution details attached. */
        public Detections withExecution(String device, String precision) {
            return new Detections(type, frameId, width, height, detections, inferenceMs, serverMs, tracking,
                    activeTracks, trackingMode, lowScoreFloor, device, precision);
        }

        /** Tracker input for a CLIENT tracking session (no Track IDs). */
        public static Detections clientTracking(long frameId, int width, int height, List<Detection> detections,
                double inferenceMs, long serverMs, Double lowScoreFloor) {
            return new Detections("detections", frameId, width, height, detections, inferenceMs, serverMs, null,
                    null, TRACKING_CLIENT, lowScoreFloor, null, null);
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
            double inferenceMs, Boolean tracking, Integer activeTracks, Boolean trackingInput, Double lowScoreFloor,
            String device, String precision) {
        public WorkerResult(long frameId, String modelKey, int width, int height, List<Detection> detections,
                double inferenceMs) {
            this(frameId, modelKey, width, height, detections, inferenceMs, null, null);
        }

        public WorkerResult(long frameId, String modelKey, int width, int height, List<Detection> detections,
                double inferenceMs, Boolean tracking, Integer activeTracks) {
            this(frameId, modelKey, width, height, detections, inferenceMs, tracking, activeTracks, null, null,
                    null, null);
        }
    }
}
