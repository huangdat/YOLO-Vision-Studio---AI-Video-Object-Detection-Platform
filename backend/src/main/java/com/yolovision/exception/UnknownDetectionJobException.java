package com.yolovision.exception;

import java.util.UUID;

/** A worker event referenced a job that does not exist in this database. */
public class UnknownDetectionJobException extends RuntimeException {

    public UnknownDetectionJobException(UUID jobId) {
        super("No detection job exists with id " + jobId);
    }
}
