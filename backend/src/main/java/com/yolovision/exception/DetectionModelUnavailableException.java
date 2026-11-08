package com.yolovision.exception;

import java.util.Map;

/**
 * The requested model cannot be used for a new job. A subclass of
 * InvalidDetectionJobException so internal callers keep one rejection type, while the
 * REST layer can distinguish an unknown model (404) from an unusable one (409).
 */
public class DetectionModelUnavailableException extends InvalidDetectionJobException {

    public enum Reason { NOT_FOUND, DISABLED, NOT_DETECTION }

    private final Reason reason;

    public DetectionModelUnavailableException(Reason reason, String message) {
        super(Map.of("modelKey", message));
        this.reason = reason;
    }

    public Reason getReason() {
        return reason;
    }
}
