package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.InferencePrecision;
import com.yolovision.entity.ProcessingMode;
import java.util.UUID;

/** Returned with 202 Accepted; status and progress are the persisted values at acceptance. */
public record DetectionJobAcceptedResponse(
        UUID jobId,
        DetectionJobStatus status,
        int progress,
        String modelKey,
        String message,
        ProcessingMode processingMode,
        InferencePrecision inferencePrecision) {

    public DetectionJobAcceptedResponse(UUID jobId, DetectionJobStatus status, int progress, String modelKey,
            String message, ProcessingMode processingMode) {
        this(jobId, status, progress, modelKey, message, processingMode, InferencePrecision.FP32);
    }
}
