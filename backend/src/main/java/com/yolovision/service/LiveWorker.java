package com.yolovision.service;

import com.yolovision.dto.live.LiveMessages.WorkerResult;
import com.yolovision.service.LiveWorkerClient.LoadResult;
import java.util.List;
import java.util.concurrent.CompletableFuture;

/** The internal live inference worker, as seen by the Live Detection session service. */
public interface LiveWorker {

    CompletableFuture<LoadResult> load(String modelKey, int imageSize);

    /**
     * One frame. With a non-null {@code trackingSessionId} the worker runs ByteTrack with the
     * state of that session only; null means Detection Only.
     */
    CompletableFuture<WorkerResult> infer(byte[] jpeg, long frameId, String modelKey, String confidence,
            int imageSize, List<Integer> classes, String trackingSessionId);

    default CompletableFuture<WorkerResult> infer(byte[] jpeg, long frameId, String modelKey, String confidence,
            int imageSize, List<Integer> classes) {
        return infer(jpeg, frameId, modelKey, confidence, imageSize, classes, null);
    }

    /** Releases the worker's tracking state of a session. Best effort and idempotent. */
    CompletableFuture<Void> endTrackingSession(String trackingSessionId);
}
