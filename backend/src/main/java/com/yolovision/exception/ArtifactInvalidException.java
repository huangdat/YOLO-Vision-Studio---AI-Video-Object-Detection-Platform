package com.yolovision.exception;

/**
 * A stored artifact exists but cannot be served safely (for example a malformed or oversized
 * result.json, or one containing path- or credential-like content). Never returned verbatim.
 */
public class ArtifactInvalidException extends RuntimeException {

    public ArtifactInvalidException(String internalReason) {
        super(internalReason);
    }
}
