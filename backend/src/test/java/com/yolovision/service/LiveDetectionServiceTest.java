package com.yolovision.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yolovision.config.LiveDetectionProperties;
import com.yolovision.dto.live.LiveMessages.Detection;
import com.yolovision.dto.live.LiveMessages.WorkerResult;
import com.yolovision.entity.ModelConfig;
import com.yolovision.repository.ModelConfigRepository;
import com.yolovision.service.LiveDetectionService.LiveConnection;
import com.yolovision.service.LiveWorkerClient.LiveWorkerException;
import com.yolovision.service.LiveWorkerClient.LoadResult;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class LiveDetectionServiceTest {

    private static final long SECOND = 1_000_000_000L;
    private final ObjectMapper mapper = new ObjectMapper();
    private final AtomicLong clock = new AtomicLong(1_000 * SECOND);
    private final FakeWorker worker = new FakeWorker();
    private final ModelConfigRepository models = mock(ModelConfigRepository.class);
    private LiveDetectionService service;

    static final class FakeConnection implements LiveConnection {
        final String id;
        final List<String> sent = new CopyOnWriteArrayList<>();
        Integer closeCode;
        boolean open = true;

        FakeConnection(String id) {
            this.id = id;
        }

        @Override
        public String id() {
            return id;
        }

        @Override
        public boolean isOpen() {
            return open;
        }

        @Override
        public void send(Object message) {
            try {
                sent.add(new ObjectMapper().writeValueAsString(message));
            } catch (Exception exception) {
                throw new IllegalStateException(exception);
            }
        }

        @Override
        public void close(int code, String reason) {
            closeCode = code;
            open = false;
        }
    }

    static final class FakeWorker implements LiveWorker {
        CompletableFuture<LoadResult> load = CompletableFuture.completedFuture(new LoadResult("yolo11n", "cpu"));
        final List<CompletableFuture<WorkerResult>> calls = new ArrayList<>();
        final List<long[]> frames = new ArrayList<>();
        final List<List<Integer>> classes = new ArrayList<>();
        String lastConfidence;

        @Override
        public CompletableFuture<LoadResult> load(String modelKey, int imageSize) {
            return load;
        }

        @Override
        public CompletableFuture<WorkerResult> infer(byte[] jpeg, long frameId, String modelKey, String confidence,
                int imageSize, List<Integer> classes) {
            CompletableFuture<WorkerResult> future = new CompletableFuture<>();
            calls.add(future);
            frames.add(new long[] {frameId, jpeg.length, imageSize});
            this.classes.add(classes);
            lastConfidence = confidence;
            return future;
        }

        void answer(int index, long frameId) {
            calls.get(index).complete(new WorkerResult(frameId, "yolo11n", 640, 480,
                    List.of(new Detection(2, "car", 0.87, List.of(120.0, 85.0, 310.0, 260.0))), 85.0));
        }
    }

    @BeforeEach
    void setUp() {
        service = new LiveDetectionService(properties(1), models, worker, mapper, clock::get);
        when(models.findByModelKey("yolo11n")).thenReturn(Optional.of(model("yolo11n", "n", "DETECT", true)));
        when(models.findByModelKey("yolov8n")).thenReturn(Optional.of(model("yolov8n", "n", "DETECT", false)));
        when(models.findByModelKey("yolo11s")).thenReturn(Optional.of(model("yolo11s", "s", "DETECT", true)));
        when(models.findByModelKey("yolo11n-seg")).thenReturn(Optional.of(model("yolo11n-seg", "n", "SEGMENT", true)));
        when(models.findByModelKey("yolo99z")).thenReturn(Optional.empty());
    }

    private static LiveDetectionProperties properties(int maxSessions) {
        return new LiveDetectionProperties("http://worker:8000", maxSessions, 5, 1024, List.of(320, 416, 640),
                List.of("n"), Duration.ofSeconds(5), Duration.ofSeconds(60), Duration.ofSeconds(30),
                Duration.ofMinutes(30), Duration.ofSeconds(5));
    }

    private static ModelConfig model(String key, String size, String task, boolean enabled) {
        ModelConfig model = new ModelConfig(key, "YOLO11", size, task, key + ".pt");
        model.setEnabled(enabled);
        return model;
    }

    private FakeConnection connect(String id) {
        FakeConnection connection = new FakeConnection(id);
        service.opened(connection);
        return connection;
    }

    private FakeConnection started(String id) {
        FakeConnection connection = connect(id);
        service.text(connection, "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\",\"confidence\":0.30,"
                + "\"imageSize\":416,\"classes\":[7,2,1]}");
        return connection;
    }

    private static ByteBuffer frame(long frameId, int jpegBytes) {
        ByteBuffer buffer = ByteBuffer.allocate(4 + jpegBytes);
        buffer.putInt((int) frameId);
        buffer.put(new byte[jpegBytes]);
        return buffer.flip();
    }

    private JsonNode last(FakeConnection connection) throws Exception {
        return mapper.readTree(connection.sent.get(connection.sent.size() - 1));
    }

    private void advance(long millis) {
        clock.addAndGet(millis * 1_000_000L);
    }

    // Session creation ----------------------------------------------------------------------------

    @Test
    void aValidStartAnswersReadyWithTheEffectiveSettings() throws Exception {
        FakeConnection connection = started("a");

        JsonNode ready = last(connection);
        assertThat(ready.path("type").asText()).isEqualTo("ready");
        assertThat(ready.path("version").asInt()).isEqualTo(1);
        assertThat(ready.path("sessionId").asText()).hasSize(36);
        assertThat(ready.path("maxFps").asInt()).isEqualTo(5);
        assertThat(ready.path("maxInFlight").asInt()).isEqualTo(1);
        assertThat(ready.path("maxFrameBytes").asInt()).isEqualTo(1024);
        assertThat(ready.path("confidence").decimalValue()).isEqualByComparingTo("0.3");
        assertThat(ready.path("classes").toString()).isEqualTo("[1,2,7]");
        assertThat(service.activeSessions()).isEqualTo(1);
        assertThat(connection.closeCode).isNull();
    }

    @Test
    void omittedSettingsUseTheLiveDefaults() throws Exception {
        FakeConnection connection = connect("a");
        service.text(connection, "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\"}");

        JsonNode ready = last(connection);
        assertThat(ready.path("imageSize").asInt()).isEqualTo(416);
        assertThat(ready.path("confidence").decimalValue()).isEqualByComparingTo("0.25");
        assertThat(ready.path("classes").toString()).isEqualTo("[1,2,3,5,7]");
    }

    @ParameterizedTest
    @ValueSource(strings = {"yolo99z:MODEL_NOT_FOUND", "yolov8n:MODEL_DISABLED", "yolo11s:MODEL_NOT_SUPPORTED",
        "yolo11n-seg:MODEL_NOT_SUPPORTED"})
    void unusableModelsAreRejectedAndClosed(String spec) throws Exception {
        String[] parts = spec.split(":");
        FakeConnection connection = connect("a");
        service.text(connection, "{\"type\":\"start\",\"version\":1,\"modelKey\":\"" + parts[0] + "\"}");

        JsonNode error = last(connection);
        assertThat(error.path("type").asText()).isEqualTo("error");
        assertThat(error.path("code").asText()).isEqualTo(parts[1]);
        assertThat(error.path("fatal").asBoolean()).isTrue();
        assertThat(connection.closeCode).isEqualTo(1008);
        assertThat(service.activeSessions()).isZero();
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "{\"type\":\"start\",\"version\":1,\"modelKey\":\"../../etc/passwd\"}:modelKey",
        "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\",\"confidence\":1.5}:confidence",
        "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\",\"confidence\":0.1234}:confidence",
        "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\",\"imageSize\":960}:imageSize",
        "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\",\"classes\":[]}:classes",
        "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\",\"classes\":[80]}:classes",
        "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\",\"classes\":[2,2]}:classes"
    })
    void invalidSettingsAreReportedPerFieldAndClosed(String spec) throws Exception {
        int split = spec.lastIndexOf(':');
        FakeConnection connection = connect("a");
        service.text(connection, spec.substring(0, split));

        JsonNode error = last(connection);
        assertThat(error.path("code").asText()).isEqualTo("INVALID_SETTINGS");
        assertThat(error.path("errors").has(spec.substring(split + 1))).isTrue();
        assertThat(connection.closeCode).isEqualTo(1008);
        assertThat(worker.calls).isEmpty();
    }

    @Test
    void unknownFieldsSuchAsFilePathsAreRejected() throws Exception {
        FakeConnection connection = connect("a");
        service.text(connection, "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\",\"weights\":\"/etc/x.pt\"}");

        assertThat(last(connection).path("code").asText()).isEqualTo("INVALID_MESSAGE");
        assertThat(connection.closeCode).isEqualTo(1008);
    }

    @Test
    void anUnsupportedProtocolVersionIsRejected() throws Exception {
        FakeConnection connection = connect("a");
        service.text(connection, "{\"type\":\"start\",\"version\":2,\"modelKey\":\"yolo11n\"}");
        assertThat(last(connection).path("code").asText()).isEqualTo("UNSUPPORTED_VERSION");
    }

    @Test
    void malformedControlMessagesAreReportedWithoutClosing() throws Exception {
        FakeConnection connection = connect("a");
        service.text(connection, "not json");
        assertThat(last(connection).path("code").asText()).isEqualTo("INVALID_MESSAGE");
        assertThat(last(connection).path("fatal").asBoolean()).isFalse();
        assertThat(connection.closeCode).isNull();
    }

    @Test
    void aSecondStartIsRejected() throws Exception {
        FakeConnection connection = started("a");
        service.text(connection, "{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\"}");
        assertThat(last(connection).path("code").asText()).isEqualTo("ALREADY_STARTED");
    }

    @Test
    void sessionCapacityIsEnforcedAndReleasedOnClose() throws Exception {
        FakeConnection first = started("a");
        FakeConnection second = started("b");

        assertThat(last(second).path("code").asText()).isEqualTo("SESSION_LIMIT_REACHED");
        assertThat(second.closeCode).isEqualTo(1008);

        service.closed(first);
        FakeConnection third = started("c");
        assertThat(last(third).path("type").asText()).isEqualTo("ready");
    }

    @ParameterizedTest
    @ValueSource(strings = {"MODEL_NOT_PREPARED", "WORKER_UNAVAILABLE", "MODEL_LOAD_FAILED"})
    void workerFailuresDuringStartAreFatalAndReleaseTheSlot(String code) throws Exception {
        worker.load = CompletableFuture.failedFuture(new LiveWorkerException(code, "worker said no"));
        FakeConnection connection = started("a");

        JsonNode error = last(connection);
        assertThat(error.path("code").asText()).isEqualTo(code);
        assertThat(error.path("fatal").asBoolean()).isTrue();
        assertThat(service.activeSessions()).isZero();
    }

    @Test
    void aLoadTimeoutIsReportedAsWorkerUnavailable() throws Exception {
        worker.load = CompletableFuture.failedFuture(new LiveWorkerException("INFERENCE_TIMEOUT", "late"));
        FakeConnection connection = started("a");
        assertThat(last(connection).path("code").asText()).isEqualTo("WORKER_UNAVAILABLE");
        assertThat(last(connection).path("message").asText()).contains("loading the model in time");
    }

    // Frames and backpressure ------------------------------------------------------------------

    @Test
    void framesBeforeReadyAreRejected() throws Exception {
        worker.load = new CompletableFuture<>(); // still loading
        FakeConnection connection = started("a");
        service.binary(connection, frame(7, 100));

        JsonNode error = last(connection);
        assertThat(error.path("code").asText()).isEqualTo("NOT_STARTED");
        assertThat(error.path("frameId").asLong()).isEqualTo(7);
        assertThat(worker.calls).isEmpty();
    }

    @Test
    void aFrameIsForwardedAndItsResultReturnedToTheSameSession() throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(42, 300));

        assertThat(worker.frames.get(0)).containsExactly(42, 300, 416);
        assertThat(worker.classes.get(0)).containsExactly(1, 2, 7);
        assertThat(worker.lastConfidence).isEqualTo("0.3");
        advance(80);
        worker.answer(0, 42);

        JsonNode result = last(connection);
        assertThat(result.path("type").asText()).isEqualTo("detections");
        assertThat(result.path("frameId").asLong()).isEqualTo(42);
        assertThat(result.path("width").asInt()).isEqualTo(640);
        assertThat(result.path("detections").get(0).path("label").asText()).isEqualTo("car");
        assertThat(result.path("detections").get(0).path("box").toString()).isEqualTo("[120.0,85.0,310.0,260.0]");
        assertThat(result.path("inferenceMs").asDouble()).isEqualTo(85.0);
        assertThat(result.path("serverMs").asLong()).isEqualTo(80);
    }

    @Test
    void frameIdsUseTheFullUnsigned32BitRange() throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(4_294_967_295L, 10));
        assertThat(worker.frames.get(0)[0]).isEqualTo(4_294_967_295L);
    }

    @Test
    void onlyOneFrameIsInFlightAndExtrasAreDroppedNotQueued() throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(1, 10));
        advance(300);
        service.binary(connection, frame(2, 10));

        JsonNode dropped = last(connection);
        assertThat(dropped.path("type").asText()).isEqualTo("dropped");
        assertThat(dropped.path("frameId").asLong()).isEqualTo(2);
        assertThat(dropped.path("reason").asText()).isEqualTo("BUSY");
        assertThat(worker.calls).hasSize(1);

        worker.answer(0, 1);
        advance(300);
        service.binary(connection, frame(3, 10));
        assertThat(worker.calls).hasSize(2);
    }

    @Test
    void framesFasterThanTheMaximumRateAreDropped() throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(1, 10));
        worker.answer(0, 1);
        advance(50); // 20 FPS > 5 FPS
        service.binary(connection, frame(2, 10));

        assertThat(last(connection).path("reason").asText()).isEqualTo("RATE_LIMITED");
        assertThat(worker.calls).hasSize(1);
        advance(200);
        service.binary(connection, frame(3, 10));
        assertThat(worker.calls).hasSize(2);
    }

    @Test
    void oversizedAndTruncatedFramesAreRejectedWithoutForwarding() throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(1, 1025));
        assertThat(last(connection).path("code").asText()).isEqualTo("FRAME_TOO_LARGE");
        service.binary(connection, ByteBuffer.wrap(new byte[] {0, 0, 1}));
        assertThat(last(connection).path("code").asText()).isEqualTo("INVALID_FRAME");
        assertThat(worker.calls).isEmpty();
        assertThat(connection.closeCode).isNull();
    }

    @ParameterizedTest
    @ValueSource(strings = {"INFERENCE_TIMEOUT", "WORKER_UNAVAILABLE", "INFERENCE_FAILED", "INVALID_FRAME"})
    void perFrameWorkerErrorsAreNonFatalAndFreeTheSlot(String code) throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(5, 10));
        worker.calls.get(0).completeExceptionally(new LiveWorkerException(code, "message for " + code));

        JsonNode error = last(connection);
        assertThat(error.path("code").asText()).isEqualTo(code);
        assertThat(error.path("frameId").asLong()).isEqualTo(5);
        assertThat(error.path("fatal").asBoolean()).isFalse();
        assertThat(connection.closeCode).isNull();
        advance(300);
        service.binary(connection, frame(6, 10));
        assertThat(worker.calls).hasSize(2);
    }

    @Test
    void aBusyWorkerIsReportedAsADroppedFrame() throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(5, 10));
        worker.calls.get(0).completeExceptionally(new LiveWorkerException("WORKER_BUSY", "busy"));
        assertThat(last(connection).path("type").asText()).isEqualTo("dropped");
    }

    @Test
    void aResultForAnotherFrameIsNeverDelivered() throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(5, 10));
        worker.answer(0, 99);
        assertThat(last(connection).path("code").asText()).isEqualTo("INFERENCE_FAILED");
    }

    @Test
    void resultsArriveOnlyAtTheirOwnSession() throws Exception {
        service = new LiveDetectionService(properties(2), models, worker, mapper, clock::get);
        FakeConnection first = started("a");
        FakeConnection second = started("b");
        service.binary(first, frame(1, 10));
        int secondBefore = second.sent.size();
        worker.answer(0, 1);

        assertThat(last(first).path("type").asText()).isEqualTo("detections");
        assertThat(second.sent).hasSize(secondBefore);
    }

    // Stop, disconnect, and timeouts ------------------------------------------------------------

    @Test
    void stopReportsCountsClosesNormallyAndIsIdempotent() throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(1, 10));
        worker.answer(0, 1);
        advance(50);
        service.binary(connection, frame(2, 10)); // dropped (rate)
        service.text(connection, "{\"type\":\"stop\"}");
        int sent = connection.sent.size();
        service.text(connection, "{\"type\":\"stop\"}");
        service.closed(connection);

        JsonNode stopped = mapper.readTree(connection.sent.get(sent - 1));
        assertThat(stopped.path("type").asText()).isEqualTo("stopped");
        assertThat(stopped.path("reason").asText()).isEqualTo("CLIENT_STOP");
        assertThat(stopped.path("processedFrames").asLong()).isEqualTo(1);
        assertThat(stopped.path("droppedFrames").asLong()).isEqualTo(1);
        assertThat(connection.sent).hasSize(sent);
        assertThat(connection.closeCode).isEqualTo(1000);
        assertThat(service.activeSessions()).isZero();
    }

    @Test
    void aDisconnectDuringInferenceDiscardsTheResultAndReleasesTheSession() throws Exception {
        FakeConnection connection = started("a");
        service.binary(connection, frame(1, 10));
        service.closed(connection);
        int sent = connection.sent.size();
        worker.answer(0, 1);

        assertThat(connection.sent).hasSize(sent);
        assertThat(service.activeSessions()).isZero();
        assertThat(worker.calls.get(0).isCancelled() || worker.calls.get(0).isDone()).isTrue();
    }

    @Test
    void aDisconnectWhileLoadingReleasesTheSlot() {
        worker.load = new CompletableFuture<>();
        FakeConnection connection = started("a");
        assertThat(service.activeSessions()).isEqualTo(1);
        service.closed(connection);
        assertThat(service.activeSessions()).isZero();
        worker.load.complete(new LoadResult("yolo11n", "cpu"));
        assertThat(connection.sent).isEmpty();
    }

    @Test
    void idleSessionsAreStopped() throws Exception {
        FakeConnection connection = started("a");
        advance(29_000);
        service.sweep();
        assertThat(connection.closeCode).isNull();
        advance(2_000);
        service.sweep();
        assertThat(last(connection).path("reason").asText()).isEqualTo("IDLE_TIMEOUT");
        assertThat(service.activeSessions()).isZero();
    }

    @Test
    void sessionsAreBoundedInDuration() throws Exception {
        FakeConnection connection = started("a");
        for (int i = 0; i < 30 * 60 / 20 + 1; i++) {
            advance(20_000);
            service.binary(connection, frame(i, 10)); // keeps the session active
            if (!worker.calls.isEmpty() && !worker.calls.get(worker.calls.size() - 1).isDone()) {
                worker.answer(worker.calls.size() - 1, i);
            }
            service.sweep();
        }
        assertThat(last(connection).path("reason").asText()).isEqualTo("MAX_DURATION");
    }

    @Test
    void connectionsThatNeverStartAreClosed() throws Exception {
        FakeConnection connection = connect("a");
        advance(31_000);
        service.sweep();
        assertThat(last(connection).path("code").asText()).isEqualTo("NOT_STARTED");
        assertThat(connection.closeCode).isEqualTo(1008);
    }

    @Test
    void shutdownStopsActiveSessionsWithGoingAway() throws Exception {
        FakeConnection connection = started("a");
        service.shutdown();
        assertThat(last(connection).path("reason").asText()).isEqualTo("SERVER_SHUTDOWN");
        assertThat(connection.closeCode).isEqualTo(1001);
    }
}
