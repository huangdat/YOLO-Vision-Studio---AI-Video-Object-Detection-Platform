package com.yolovision.exception;

public class DetectionJobNotFoundException extends RuntimeException {

    public DetectionJobNotFoundException() {
        super("The requested detection job does not exist.");
    }
}
