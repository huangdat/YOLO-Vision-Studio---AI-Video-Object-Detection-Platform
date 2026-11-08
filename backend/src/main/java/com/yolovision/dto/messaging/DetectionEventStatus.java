package com.yolovision.dto.messaging;

/** Statuses a worker may report; PENDING, QUEUED, and CANCELLED are backend-owned. */
public enum DetectionEventStatus {
    DOWNLOADING,
    DETECTING,
    ENCODING,
    UPLOADING,
    COMPLETED,
    FAILED;

    public boolean isTerminal() {
        return this == COMPLETED || this == FAILED;
    }
}
