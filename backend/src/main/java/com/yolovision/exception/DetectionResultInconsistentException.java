package com.yolovision.exception;

import java.util.UUID;

/** A COMPLETED job has no result row: a server-side consistency error, never a fabricated result. */
public class DetectionResultInconsistentException extends RuntimeException {

    public DetectionResultInconsistentException(UUID jobId) {
        super("Completed detection job " + jobId + " has no result metadata");
    }
}
