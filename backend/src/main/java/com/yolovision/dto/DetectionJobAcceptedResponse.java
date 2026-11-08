package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import java.util.UUID;

/** Returned with 202 Accepted; status and progress are the persisted values at acceptance. */
public record DetectionJobAcceptedResponse(
        UUID jobId,
        DetectionJobStatus status,
        int progress,
        String modelKey,
        String message) {
}
