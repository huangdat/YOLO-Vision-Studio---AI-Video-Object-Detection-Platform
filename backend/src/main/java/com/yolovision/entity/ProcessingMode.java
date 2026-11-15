package com.yolovision.entity;

/**
 * How a job's frames are analysed. DETECTION_ONLY treats each frame independently (the
 * behaviour of every job created before tracking existed). DETECTION_TRACKING also runs
 * ByteTrack in the Python worker, an online tracker, so detections keep a Track ID that is
 * scoped to the job. Tracking itself never runs in Spring Boot.
 */
public enum ProcessingMode {
    DETECTION_ONLY,
    DETECTION_TRACKING;

    public static final String TRACKER = "bytetrack";

    public boolean tracking() {
        return this == DETECTION_TRACKING;
    }
}
