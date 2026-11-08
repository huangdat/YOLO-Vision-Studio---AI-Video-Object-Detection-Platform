package com.yolovision.exception;

/** The configured maximum number of concurrent progress streams is in use. */
public class StreamCapacityExceededException extends RuntimeException {

    public StreamCapacityExceededException() {
        super("Too many progress streams are open. Retry later or poll the job status.");
    }
}
