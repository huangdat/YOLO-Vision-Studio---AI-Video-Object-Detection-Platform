package com.yolovision.exception;

public class ModelNotFoundException extends RuntimeException {

    public ModelNotFoundException() {
        super("The requested model is not registered.");
    }
}
