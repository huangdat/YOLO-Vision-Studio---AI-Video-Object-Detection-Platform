package com.yolovision.entity;

/** Persisted by name. Legal transitions are enforced by DetectionJobLifecycleService. */
public enum DetectionJobStatus {
    PENDING,
    QUEUED,
    DOWNLOADING,
    DETECTING,
    ENCODING,
    UPLOADING,
    COMPLETED,
    FAILED,
    CANCELLED
}
