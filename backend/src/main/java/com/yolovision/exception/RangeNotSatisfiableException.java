package com.yolovision.exception;

/** The requested byte range starts beyond the artifact; answered with 416 and {@code bytes *}{@code /size}. */
public class RangeNotSatisfiableException extends RuntimeException {

    private final long size;

    public RangeNotSatisfiableException(long size) {
        super("The requested byte range cannot be satisfied.");
        this.size = size;
    }

    public long getSize() {
        return size;
    }
}
