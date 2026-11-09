package com.yolovision.exception;

/**
 * Reading from storage failed after the response was committed. The status can no longer change,
 * so the exception is propagated to the servlet container, which aborts the connection: the
 * client sees an incomplete transfer instead of a truncated body reported as success.
 */
public class ArtifactTransferException extends RuntimeException {

    public ArtifactTransferException(String message, Throwable cause) {
        super(message, cause);
    }
}
