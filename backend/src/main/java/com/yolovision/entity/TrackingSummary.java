package com.yolovision.entity;

import java.util.Map;

/**
 * Tracking totals of a DETECTION_TRACKING result, as reported by the worker. Unique Track IDs
 * are the IDs ByteTrack assigned within the job; ID switches and fragmentation mean they are
 * not guaranteed to equal the number of physical objects. Per-track details are in result.json.
 */
public record TrackingSummary(
        String tracker,
        long uniqueTrackIds,
        int maxActiveTracks,
        long trackedDetections,
        Map<String, Long> uniqueTrackIdsByClass) {

    public TrackingSummary {
        uniqueTrackIdsByClass = uniqueTrackIdsByClass == null ? Map.of() : Map.copyOf(uniqueTrackIdsByClass);
    }
}
