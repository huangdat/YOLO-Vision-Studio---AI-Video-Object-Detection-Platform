package com.yolovision.exception;

/**
 * A completed job's artifact is not recorded, does not belong to the job, or is missing from
 * storage. The client message is fixed; the detailed reason is logged server-side only.
 */
public class ArtifactNotFoundException extends RuntimeException {

    public ArtifactNotFoundException(String internalReason) {
        super(internalReason);
    }
}
