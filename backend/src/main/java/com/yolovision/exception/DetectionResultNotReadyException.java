package com.yolovision.exception;

import com.yolovision.entity.DetectionJobStatus;

/** The job exists but has not completed successfully, so no result metadata exists yet. */
public class DetectionResultNotReadyException extends RuntimeException {

    private final DetectionJobStatus status;

    public DetectionResultNotReadyException(DetectionJobStatus status) {
        super("Detection results are not available while the job is " + status + ".");
        this.status = status;
    }

    public DetectionJobStatus getStatus() {
        return status;
    }
}
