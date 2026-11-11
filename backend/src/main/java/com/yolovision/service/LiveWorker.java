package com.yolovision.service;

import com.yolovision.dto.live.LiveMessages.WorkerResult;
import com.yolovision.service.LiveWorkerClient.LoadResult;
import java.util.List;
import java.util.concurrent.CompletableFuture;

/** The internal live inference worker, as seen by the Live Detection session service. */
public interface LiveWorker {

    CompletableFuture<LoadResult> load(String modelKey, int imageSize);

    CompletableFuture<WorkerResult> infer(byte[] jpeg, long frameId, String modelKey, String confidence,
            int imageSize, List<Integer> classes);
}
