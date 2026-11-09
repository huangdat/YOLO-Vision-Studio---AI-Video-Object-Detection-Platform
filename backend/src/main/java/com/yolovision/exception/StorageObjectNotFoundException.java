package com.yolovision.exception;

/** Internal: a referenced object does not exist. Mapped by the artifact service, never returned as-is. */
public class StorageObjectNotFoundException extends RuntimeException {

    public StorageObjectNotFoundException() {
        super("The stored object does not exist.");
    }
}
