package com.yolovision.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yolovision.config.LiveDetectionProperties;
import com.yolovision.dto.live.LiveMessages.WorkerResult;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Non-blocking HTTP client for the internal ai-live-worker. Calls never run on WebSocket I/O
 * threads and never wait longer than the configured timeouts. Frames are sent as raw JPEG.
 */
@Component
public class LiveWorkerClient implements LiveWorker {

    private static final Logger LOG = LoggerFactory.getLogger(LiveWorkerClient.class);

    /** A failed worker call with a stable, client-safe code. */
    public static final class LiveWorkerException extends RuntimeException {

        private final String code;

        public LiveWorkerException(String code, String message) {
            super(message);
            this.code = code;
        }

        public String getCode() {
            return code;
        }
    }

    public record LoadResult(String modelKey, String device) {
    }

    private final LiveDetectionProperties properties;
    private final ObjectMapper objectMapper;
    private final ExecutorService executor;
    private final HttpClient http;
    private final String baseUrl;

    public LiveWorkerClient(LiveDetectionProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        // Bounded: at most maxSessions frames are in flight, plus one load per session.
        this.executor = Executors.newFixedThreadPool(Math.max(2, properties.maxSessions() * 2), runnable -> {
            Thread thread = new Thread(runnable, "live-worker-client");
            thread.setDaemon(true);
            return thread;
        });
        this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).executor(executor)
                .version(HttpClient.Version.HTTP_1_1).build();
        this.baseUrl = properties.workerUrl().replaceAll("/+$", "");
    }

    @Override
    public CompletableFuture<LoadResult> load(String modelKey, int imageSize) {
        HttpRequest request = HttpRequest.newBuilder(
                        URI.create(baseUrl + "/internal/live/models/" + encode(modelKey) + "/load?imageSize=" + imageSize))
                .timeout(properties.loadTimeout())
                .POST(HttpRequest.BodyPublishers.noBody())
                .build();
        return send(request).thenApply(body -> {
            JsonNode node = parse(body);
            return new LoadResult(node.path("modelKey").asText(modelKey), node.path("device").asText("unknown"));
        });
    }

    @Override
    public CompletableFuture<WorkerResult> infer(byte[] jpeg, long frameId, String modelKey, String confidence,
            int imageSize, List<Integer> classes) {
        String query = "modelKey=" + encode(modelKey) + "&frameId=" + frameId + "&confidence=" + confidence
                + "&imageSize=" + imageSize + "&classes="
                + classes.stream().map(String::valueOf).collect(Collectors.joining(","));
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + "/internal/live/infer?" + query))
                .timeout(properties.inferenceTimeout())
                .header("Content-Type", "image/jpeg")
                .POST(HttpRequest.BodyPublishers.ofByteArray(jpeg))
                .build();
        return send(request).thenApply(body -> {
            try {
                return objectMapper.readValue(body, WorkerResult.class);
            } catch (IOException exception) {
                throw new LiveWorkerException("INFERENCE_FAILED", "The live worker returned an invalid response.");
            }
        });
    }

    private CompletableFuture<String> send(HttpRequest request) {
        return http.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                .handle((response, failure) -> {
                    if (failure != null) {
                        throw translate(failure);
                    }
                    if (response.statusCode() / 100 == 2) {
                        return response.body();
                    }
                    throw workerError(response);
                });
    }

    private LiveWorkerException workerError(HttpResponse<String> response) {
        JsonNode error = parse(response.body()).path("error");
        String code = error.path("code").asText("");
        String message = error.path("message").asText("");
        return switch (code) {
            case "MODEL_NOT_PREPARED", "MODEL_NOT_SUPPORTED", "INVALID_FRAME", "FRAME_TOO_LARGE",
                    "INVALID_PARAMETERS", "INFERENCE_FAILED", "MODEL_LOAD_FAILED" ->
                    new LiveWorkerException(code, message.isBlank() ? "The live worker rejected the request." : message);
            case "WORKER_BUSY" -> new LiveWorkerException("WORKER_BUSY", "The live worker is busy.");
            default -> {
                LOG.warn("Live worker answered HTTP {} without a known error code", response.statusCode());
                yield new LiveWorkerException("WORKER_UNAVAILABLE", "The live detection worker is unavailable.");
            }
        };
    }

    private static LiveWorkerException translate(Throwable failure) {
        Throwable cause = failure instanceof CompletionException && failure.getCause() != null
                ? failure.getCause() : failure;
        if (cause instanceof LiveWorkerException workerException) {
            return workerException;
        }
        if (cause instanceof HttpTimeoutException) {
            return new LiveWorkerException("INFERENCE_TIMEOUT", "The live worker did not answer in time.");
        }
        // Connection refused, DNS failure, reset: log the type only (messages contain addresses).
        LOG.debug("Live worker call failed: {}", cause.getClass().getSimpleName());
        return new LiveWorkerException("WORKER_UNAVAILABLE", "The live detection worker is unavailable.");
    }

    private JsonNode parse(String body) {
        try {
            return objectMapper.readTree(body == null || body.isBlank() ? "{}" : body);
        } catch (IOException exception) {
            return objectMapper.createObjectNode();
        }
    }

    private static String encode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    @PreDestroy
    void shutdown() {
        executor.shutdownNow();
    }
}
