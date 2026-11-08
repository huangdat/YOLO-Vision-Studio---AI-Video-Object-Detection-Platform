package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import java.time.Instant;
import java.util.UUID;

/**
 * SSE payload built only from persisted job state. {@code timestamp} is the job's last
 * update time; errorCode and message carry the stored, sanitized failure details.
 */
public record DetectionProgressEvent(
        UUID jobId,
        DetectionJobStatus status,
        int progress,
        String message,
        String errorCode,
        Instant timestamp) {
}
