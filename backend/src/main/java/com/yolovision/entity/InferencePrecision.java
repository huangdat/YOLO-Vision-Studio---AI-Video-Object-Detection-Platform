package com.yolovision.entity;

import java.util.Locale;

/**
 * Per-job inference precision. FP32 (the default) runs the PyTorch checkpoint; INT8 runs the
 * worker's validated OpenVINO INT8 artifact (CPU only, experimental). Inference itself never runs
 * in Spring Boot: the precision travels to the worker in the job command, and the worker reports
 * the precision that actually ran.
 */
public enum InferencePrecision {
    FP32,
    INT8;

    /** Case-insensitive parse ({@code fp32}, {@code INT8}); null for an unknown value. */
    public static InferencePrecision parse(String value) {
        if (value == null) {
            return null;
        }
        try {
            return valueOf(value.strip().toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException exception) {
            return null;
        }
    }
}
