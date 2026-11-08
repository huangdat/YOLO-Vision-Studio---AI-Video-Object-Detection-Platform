package com.yolovision.entity;

/** Persisted by name; processing transitions are defined in a later phase. */
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
