package com.yolovision.repository;

import com.yolovision.entity.DetectionJobStatus;
import java.time.Instant;
import java.util.UUID;

/** Narrow projection read by the progress stream poller (no entity or association loading). */
public interface DetectionJobProgressView {

    UUID getId();

    DetectionJobStatus getStatus();

    int getProgress();

    String getErrorCode();

    String getErrorMessage();

    Instant getUpdatedAt();
}
