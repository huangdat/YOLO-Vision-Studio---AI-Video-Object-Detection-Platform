package com.yolovision.exception;

import java.util.Map;

/** A submission was rejected before any job or message was created. */
public class InvalidDetectionJobException extends RuntimeException {

    private final Map<String, String> errors;

    public InvalidDetectionJobException(Map<String, String> errors) {
        super("Detection job configuration is invalid: " + errors.keySet());
        this.errors = Map.copyOf(errors);
    }

    public static InvalidDetectionJobException of(String field, String reason) {
        return new InvalidDetectionJobException(Map.of(field, reason));
    }

    public Map<String, String> getErrors() {
        return errors;
    }
}
