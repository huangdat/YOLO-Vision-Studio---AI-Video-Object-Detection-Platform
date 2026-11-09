package com.yolovision.service;

import java.util.UUID;
import org.springframework.http.MediaType;

/**
 * The artifacts a completed job exposes. Object names follow the worker's convention
 * ({@code <prefix>/<jobId>/detected.mp4} and {@code .../result.json}); response types are fixed
 * here rather than taken from storage metadata.
 */
public enum DetectionArtifact {

    VIDEO("detected.mp4", MediaType.valueOf("video/mp4"), ".mp4"),
    RESULT_JSON("result.json", MediaType.APPLICATION_JSON, "-result.json");

    private final String objectName;
    private final MediaType mediaType;
    private final String filenameSuffix;

    DetectionArtifact(String objectName, MediaType mediaType, String filenameSuffix) {
        this.objectName = objectName;
        this.mediaType = mediaType;
        this.filenameSuffix = filenameSuffix;
    }

    public String objectName() {
        return objectName;
    }

    public MediaType mediaType() {
        return mediaType;
    }

    /** Server-generated download name: only the canonical UUID, never client input. */
    public String filename(UUID jobId) {
        return "detection-" + jobId + filenameSuffix;
    }
}
