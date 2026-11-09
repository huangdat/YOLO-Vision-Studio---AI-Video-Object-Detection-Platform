package com.yolovision.exception;

/** Object storage could not be reached or is not configured. The message is client-safe. */
public class StorageUnavailableException extends RuntimeException {

    public StorageUnavailableException(Throwable cause) {
        super("Artifact storage is temporarily unavailable.", cause);
    }

    public StorageUnavailableException() {
        super("Artifact storage is temporarily unavailable.");
    }
}
