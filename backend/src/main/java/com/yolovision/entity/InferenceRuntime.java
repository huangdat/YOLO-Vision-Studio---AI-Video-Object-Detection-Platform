package com.yolovision.entity;

/** The inference runtime a worker actually used for a job, as reported in its completion event. */
public enum InferenceRuntime {
    PYTORCH,
    OPENVINO
}
