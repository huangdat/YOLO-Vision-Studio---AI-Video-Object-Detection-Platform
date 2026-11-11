package com.yolovision.service;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import com.yolovision.config.LiveDetectionProperties;
import com.yolovision.dto.live.LiveMessages;
import com.yolovision.dto.live.LiveMessages.Detections;
import com.yolovision.dto.live.LiveMessages.Dropped;
import com.yolovision.dto.live.LiveMessages.Ready;
import com.yolovision.dto.live.LiveMessages.StartRequest;
import com.yolovision.dto.live.LiveMessages.Stopped;
import com.yolovision.dto.live.LiveMessages.WorkerResult;
import com.yolovision.entity.ModelConfig;
import com.yolovision.repository.ModelConfigRepository;
import com.yolovision.service.LiveWorkerClient.LiveWorkerException;
import jakarta.annotation.PreDestroy;
import java.math.BigDecimal;
import java.nio.ByteBuffer;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.LongSupplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * Live Detection sessions: validation, capacity, and strict backpressure (one frame in flight,
 * a maximum frame rate, bounded frames). Frames are forwarded to the internal live worker and
 * never stored. Results are delivered only to the connection that sent the frame. Every exit
 * path (stop, close, error, timeout, shutdown) goes through one idempotent cleanup.
 */
@Service
public class LiveDetectionService {

    /** One browser WebSocket, as seen by the service (thread-safe sends). */
    public interface LiveConnection {

        String id();

        boolean isOpen();

        void send(Object message);

        void close(int code, String reason);
    }

    public static final int CLOSE_NORMAL = 1000;
    public static final int CLOSE_GOING_AWAY = 1001;
    public static final int CLOSE_POLICY = 1008;
    public static final int CLOSE_INTERNAL = 1011;

    private static final Logger LOG = LoggerFactory.getLogger(LiveDetectionService.class);
    private static final int MAX_CLASS_ID = 79;

    enum State { CONNECTED, STARTING, ACTIVE, CLOSED }

    static final class Session {
        final LiveConnection connection;
        final String sessionId = UUID.randomUUID().toString();
        final long openedNanos;
        volatile State state = State.CONNECTED;
        volatile long startedNanos;
        volatile long lastActivityNanos;
        volatile long lastAcceptedFrameNanos = Long.MIN_VALUE / 2;
        volatile Settings settings;
        volatile CompletableFuture<?> pending;
        final AtomicBoolean inFlight = new AtomicBoolean();
        final AtomicBoolean holdsSlot = new AtomicBoolean();
        final AtomicBoolean closed = new AtomicBoolean();
        final AtomicLong processed = new AtomicLong();
        final AtomicLong dropped = new AtomicLong();

        Session(LiveConnection connection, long now) {
            this.connection = connection;
            this.openedNanos = now;
            this.lastActivityNanos = now;
        }
    }

    record Settings(String modelKey, BigDecimal confidence, int imageSize, List<Integer> classes) {
    }

    private final LiveDetectionProperties properties;
    private final ModelConfigRepository models;
    private final LiveWorker worker;
    private final ObjectMapper objectMapper;
    private final ObjectReader startReader;
    private final LongSupplier nanoTime;
    private final Semaphore capacity;
    private final Map<String, Session> sessions = new ConcurrentHashMap<>();

    @Autowired
    public LiveDetectionService(LiveDetectionProperties properties, ModelConfigRepository models, LiveWorker worker,
            ObjectMapper objectMapper) {
        this(properties, models, worker, objectMapper, System::nanoTime);
    }

    LiveDetectionService(LiveDetectionProperties properties, ModelConfigRepository models, LiveWorker worker,
            ObjectMapper objectMapper, LongSupplier nanoTime) {
        this.properties = properties;
        this.models = models;
        this.worker = worker;
        this.objectMapper = objectMapper;
        this.startReader = objectMapper.readerFor(StartRequest.class)
                .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
        this.nanoTime = nanoTime;
        this.capacity = new Semaphore(properties.maxSessions());
    }

    // Connection lifecycle --------------------------------------------------------------------

    public void opened(LiveConnection connection) {
        sessions.put(connection.id(), new Session(connection, nanoTime.getAsLong()));
    }

    public void closed(LiveConnection connection) {
        Session session = sessions.get(connection.id());
        if (session != null) {
            release(session, "connection closed");
        }
    }

    public int activeSessions() {
        return properties.maxSessions() - capacity.availablePermits();
    }

    // Control messages ------------------------------------------------------------------------

    public void text(LiveConnection connection, String payload) {
        Session session = sessions.get(connection.id());
        if (session == null || session.state == State.CLOSED) {
            return;
        }
        JsonNode message;
        try {
            message = objectMapper.readTree(payload);
        } catch (Exception exception) {
            message = null;
        }
        String type = message != null && message.isObject() ? message.path("type").asText("") : "";
        switch (type) {
            case "start" -> start(session, message);
            case "stop" -> stop(session, "CLIENT_STOP");
            default -> session.connection.send(LiveMessages.Error.of("INVALID_MESSAGE",
                    "Unknown or malformed control message.", false));
        }
    }

    private void start(Session session, JsonNode message) {
        if (session.state != State.CONNECTED) {
            session.connection.send(LiveMessages.Error.of("ALREADY_STARTED", "The session is already started.", false));
            return;
        }
        StartRequest request;
        try {
            request = startReader.readValue(message);
        } catch (Exception exception) {
            fail(session, "INVALID_MESSAGE", "The start message is malformed or has unsupported fields.");
            return;
        }
        if (request.version() == null || request.version() != LiveMessages.PROTOCOL_VERSION) {
            fail(session, "UNSUPPORTED_VERSION", "Only protocol version 1 is supported.");
            return;
        }
        Map<String, String> errors = new LinkedHashMap<>();
        Settings settings = validate(request, errors);
        if (!errors.isEmpty()) {
            session.connection.send(LiveMessages.Error.invalidSettings(errors));
            session.connection.close(CLOSE_POLICY, "Invalid settings");
            release(session, "invalid settings");
            return;
        }
        Optional<ModelConfig> model = models.findByModelKey(settings.modelKey());
        if (model.isEmpty()) {
            fail(session, "MODEL_NOT_FOUND", "The requested model is not registered.");
            return;
        }
        if (!model.get().isEnabled()) {
            fail(session, "MODEL_DISABLED", "The requested model is not enabled for detection.");
            return;
        }
        if (!"DETECT".equals(model.get().getTaskType())
                || !properties.modelSizes().contains(model.get().getModelSize())) {
            fail(session, "MODEL_NOT_SUPPORTED", "Live Detection supports only lightweight detection models ("
                    + String.join(", ", properties.modelSizes()) + " size).");
            return;
        }
        if (!capacity.tryAcquire()) {
            fail(session, "SESSION_LIMIT_REACHED", "Another live session is already running. Try again later.");
            return;
        }
        session.holdsSlot.set(true);
        session.settings = settings;
        session.state = State.STARTING;
        CompletableFuture<?> load = worker.load(settings.modelKey(), settings.imageSize())
                .whenComplete((loaded, failure) -> {
                    session.pending = null;
                    if (session.state != State.STARTING) {
                        return; // closed while loading
                    }
                    if (failure != null) {
                        LiveWorkerException error = unwrap(failure);
                        String code = "INFERENCE_TIMEOUT".equals(error.getCode()) ? "WORKER_UNAVAILABLE" : error.getCode();
                        fail(session, code, "INFERENCE_TIMEOUT".equals(error.getCode())
                                ? "The live worker did not finish loading the model in time." : error.getMessage());
                        return;
                    }
                    long now = nanoTime.getAsLong();
                    session.startedNanos = now;
                    session.lastActivityNanos = now;
                    session.state = State.ACTIVE;
                    LOG.info("Live session {} started: model {}, {} px, {} classes", session.sessionId,
                            settings.modelKey(), settings.imageSize(), settings.classes().size());
                    session.connection.send(new Ready(session.sessionId, settings.modelKey(), properties.maxFps(),
                            properties.maxFrameBytes(), settings.imageSize(), settings.confidence(),
                            settings.classes()));
                });
        session.pending = load;
    }

    private Settings validate(StartRequest request, Map<String, String> errors) {
        String modelKey = request.modelKey();
        if (modelKey == null || !modelKey.matches("^[a-z0-9][a-z0-9_-]{0,63}$")) {
            errors.put("modelKey", "must be a registered model key");
        }
        BigDecimal confidence = request.confidence() == null ? new BigDecimal("0.25") : request.confidence();
        if (confidence.compareTo(BigDecimal.ZERO) < 0 || confidence.compareTo(BigDecimal.ONE) > 0
                || confidence.stripTrailingZeros().scale() > 3) {
            errors.put("confidence", "must be between 0 and 1 with at most three decimals");
        }
        int imageSize = request.imageSize() == null ? 416 : request.imageSize();
        if (!properties.imageSizes().contains(imageSize)) {
            errors.put("imageSize", "must be one of " + properties.imageSizes());
        }
        List<Integer> classes = request.classes() == null ? List.of(1, 2, 3, 5, 7) : request.classes();
        Set<Integer> unique = new TreeSet<>();
        boolean invalid = classes.isEmpty() || classes.size() > MAX_CLASS_ID + 1;
        for (Integer id : classes) {
            if (id == null || id < 0 || id > MAX_CLASS_ID || !unique.add(id)) {
                invalid = true;
            }
        }
        if (invalid) {
            errors.put("classes", "must contain 1-80 unique COCO class IDs between 0 and 79");
        }
        return new Settings(modelKey, confidence.stripTrailingZeros(), imageSize, List.copyOf(unique));
    }

    // Frames ------------------------------------------------------------------------------------

    public void binary(LiveConnection connection, ByteBuffer payload) {
        Session session = sessions.get(connection.id());
        if (session == null || session.state == State.CLOSED) {
            return;
        }
        if (payload.remaining() < 5) {
            session.connection.send(LiveMessages.Error.of("INVALID_FRAME",
                    "A frame is a 4-byte frame ID followed by JPEG data.", false));
            return;
        }
        long frameId = payload.getInt() & 0xFFFFFFFFL;
        if (session.state != State.ACTIVE) {
            session.connection.send(LiveMessages.Error.forFrame(frameId, "NOT_STARTED",
                    "Send a start message and wait for ready before sending frames."));
            return;
        }
        long now = nanoTime.getAsLong();
        session.lastActivityNanos = now;
        if (payload.remaining() > properties.maxFrameBytes()) {
            session.dropped.incrementAndGet();
            session.connection.send(LiveMessages.Error.forFrame(frameId, "FRAME_TOO_LARGE",
                    "The frame exceeds " + properties.maxFrameBytes() + " bytes."));
            return;
        }
        if (now - session.lastAcceptedFrameNanos < properties.minFrameIntervalNanos()) {
            session.dropped.incrementAndGet();
            session.connection.send(Dropped.rateLimited(frameId));
            return;
        }
        if (!session.inFlight.compareAndSet(false, true)) {
            session.dropped.incrementAndGet();
            session.connection.send(Dropped.busy(frameId));
            return;
        }
        session.lastAcceptedFrameNanos = now;
        byte[] jpeg = new byte[payload.remaining()];
        payload.get(jpeg);
        Settings settings = session.settings;
        long started = nanoTime.getAsLong();
        CompletableFuture<WorkerResult> call;
        try {
            call = worker.infer(jpeg, frameId, settings.modelKey(), settings.confidence().toPlainString(),
                    settings.imageSize(), settings.classes());
        } catch (RuntimeException exception) {
            call = CompletableFuture.failedFuture(exception);
        }
        session.pending = call;
        call.whenComplete((result, failure) -> {
            session.pending = null;
            session.inFlight.set(false);
            if (session.state != State.ACTIVE) {
                return; // stopped or disconnected meanwhile: the result is discarded
            }
            if (failure != null) {
                LiveWorkerException error = unwrap(failure);
                if ("WORKER_BUSY".equals(error.getCode())) {
                    session.dropped.incrementAndGet();
                    session.connection.send(Dropped.busy(frameId));
                } else {
                    session.connection.send(LiveMessages.Error.forFrame(frameId, error.getCode(), error.getMessage()));
                }
                return;
            }
            if (result.frameId() != frameId) {
                session.connection.send(LiveMessages.Error.forFrame(frameId, "INFERENCE_FAILED",
                        "The live worker answered for a different frame."));
                return;
            }
            session.processed.incrementAndGet();
            long serverMs = TimeUnit.NANOSECONDS.toMillis(nanoTime.getAsLong() - started);
            session.connection.send(new Detections(frameId, result.width(), result.height(),
                    result.detections() == null ? List.of() : result.detections(), result.inferenceMs(), serverMs));
        });
    }

    // Stop, timeouts, cleanup -------------------------------------------------------------------

    void stop(Session session, String reason) {
        if (session.closed.get()) {
            return;
        }
        session.connection.send(new Stopped(reason, session.processed.get(), session.dropped.get()));
        session.connection.close(reason.equals("SERVER_SHUTDOWN") ? CLOSE_GOING_AWAY : CLOSE_NORMAL, reason);
        release(session, reason);
    }

    private void fail(Session session, String code, String message) {
        session.connection.send(LiveMessages.Error.of(code, message, true));
        session.connection.close(CLOSE_POLICY, code);
        release(session, code);
    }

    private void release(Session session, String reason) {
        if (!session.closed.compareAndSet(false, true)) {
            return;
        }
        State previous = session.state;
        session.state = State.CLOSED;
        sessions.remove(session.connection.id(), session);
        CompletableFuture<?> pending = session.pending;
        if (pending != null) {
            pending.cancel(true);
        }
        if (session.holdsSlot.compareAndSet(true, false)) {
            capacity.release();
        }
        if (previous == State.ACTIVE || previous == State.STARTING) {
            LOG.info("Live session {} ended ({}): {} frames processed, {} dropped", session.sessionId, reason,
                    session.processed.get(), session.dropped.get());
        }
    }

    /** Ends idle, abandoned, and over-long sessions. */
    @Scheduled(fixedDelayString = "${app.live.sweep-interval:5s}")
    public void sweep() {
        long now = nanoTime.getAsLong();
        long idle = properties.idleTimeout().toNanos();
        for (Session session : sessions.values()) {
            if (session.state == State.ACTIVE && now - session.startedNanos > properties.maxSessionDuration().toNanos()) {
                stop(session, "MAX_DURATION");
            } else if (session.state == State.ACTIVE && now - session.lastActivityNanos > idle) {
                stop(session, "IDLE_TIMEOUT");
            } else if (session.state == State.CONNECTED && now - session.openedNanos > idle) {
                fail(session, "NOT_STARTED", "No start message was received in time.");
            }
        }
    }

    @PreDestroy
    void shutdown() {
        for (Session session : sessions.values()) {
            if (session.state == State.ACTIVE) {
                stop(session, "SERVER_SHUTDOWN");
            } else {
                session.connection.close(CLOSE_GOING_AWAY, "SERVER_SHUTDOWN");
                release(session, "shutdown");
            }
        }
    }

    private static LiveWorkerException unwrap(Throwable failure) {
        Throwable cause = failure instanceof CompletionException && failure.getCause() != null
                ? failure.getCause() : failure;
        if (cause instanceof LiveWorkerException workerException) {
            return workerException;
        }
        if (cause instanceof java.util.concurrent.CancellationException) {
            return new LiveWorkerException("WORKER_UNAVAILABLE", "The request to the live worker was cancelled.");
        }
        LOG.warn("Unexpected live worker failure: {}", cause.getClass().getSimpleName());
        return new LiveWorkerException("INFERENCE_FAILED", "Live inference failed.");
    }
}
