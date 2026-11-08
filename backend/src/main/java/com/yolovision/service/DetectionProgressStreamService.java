package com.yolovision.service;

import com.yolovision.config.DetectionStreamProperties;
import com.yolovision.dto.DetectionProgressEvent;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.exception.DetectionJobNotFoundException;
import com.yolovision.exception.StreamCapacityExceededException;
import com.yolovision.repository.DetectionJobProgressView;
import com.yolovision.repository.DetectionJobRepository;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.time.Clock;
import java.time.Instant;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.SmartLifecycle;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * Pushes persisted job state to browsers over Server-Sent Events.
 *
 * <p>PostgreSQL is the source of truth: the Phase 05 RabbitMQ consumer updates job rows,
 * and one shared poller thread reads the state of every watched job with a single query
 * per tick. Each stream receives an immediate snapshot, then an event only when status,
 * progress, or error code changes, plus periodic heartbeat comments. Streams close after a
 * terminal state. There is no event log, so a reconnecting client receives the latest
 * snapshot rather than a replay of missed transitions.
 */
@Service
public class DetectionProgressStreamService implements SmartLifecycle {

    public static final String PROGRESS_EVENT = "detection.progress";
    public static final String COMPLETED_EVENT = "detection.completed";
    public static final String FAILED_EVENT = "detection.failed";
    public static final String CANCELLED_EVENT = "detection.cancelled";

    private static final Logger LOG = LoggerFactory.getLogger(DetectionProgressStreamService.class);
    private static final Set<DetectionJobStatus> TERMINAL = EnumSet.of(
            DetectionJobStatus.COMPLETED, DetectionJobStatus.FAILED, DetectionJobStatus.CANCELLED);

    private final DetectionJobRepository jobs;
    private final DetectionStreamProperties settings;
    private final Clock clock;
    private final Function<Long, SseEmitter> emitterFactory;
    private final Map<UUID, Subscriber> subscribers = new ConcurrentHashMap<>();
    private final AtomicInteger open = new AtomicInteger();
    private volatile ScheduledExecutorService poller;

    @Autowired
    public DetectionProgressStreamService(DetectionJobRepository jobs, DetectionStreamProperties settings) {
        this(jobs, settings, Clock.systemUTC(), SseEmitter::new);
    }

    DetectionProgressStreamService(DetectionJobRepository jobs, DetectionStreamProperties settings, Clock clock,
            Function<Long, SseEmitter> emitterFactory) {
        this.jobs = jobs;
        this.settings = settings;
        this.clock = clock;
        this.emitterFactory = emitterFactory;
    }

    /** Validates the job, reserves a bounded slot, and sends the current snapshot at once. */
    public SseEmitter subscribe(UUID jobId) {
        DetectionJobProgressView snapshot = jobs.findProgressByIdIn(List.of(jobId)).stream().findFirst()
                .orElseThrow(DetectionJobNotFoundException::new);
        if (open.incrementAndGet() > settings.maxConnections()) {
            open.decrementAndGet();
            throw new StreamCapacityExceededException();
        }
        SseEmitter emitter;
        Subscriber subscriber;
        try {
            emitter = emitterFactory.apply(settings.timeout().toMillis());
            subscriber = new Subscriber(UUID.randomUUID(), jobId, emitter);
            emitter.onCompletion(() -> release(subscriber));
            emitter.onTimeout(() -> close(subscriber));
            emitter.onError(error -> release(subscriber));
            subscribers.put(subscriber.id, subscriber);
        } catch (RuntimeException exception) {
            open.decrementAndGet();
            throw exception;
        }
        deliver(subscriber, snapshot);
        return emitter;
    }

    /** One poll tick: a single query for all watched jobs, then per-stream delivery. */
    public void poll() {
        if (subscribers.isEmpty()) {
            return;
        }
        Set<UUID> watched = subscribers.values().stream().map(subscriber -> subscriber.jobId)
                .collect(Collectors.toSet());
        Map<UUID, DetectionJobProgressView> current = jobs.findProgressByIdIn(watched).stream()
                .collect(Collectors.toMap(DetectionJobProgressView::getId, Function.identity()));
        for (Subscriber subscriber : List.copyOf(subscribers.values())) {
            DetectionJobProgressView view = current.get(subscriber.jobId);
            if (view == null) {
                close(subscriber); // the job no longer exists
            } else {
                deliver(subscriber, view);
            }
        }
    }

    public int openStreams() {
        return open.get();
    }

    private void deliver(Subscriber subscriber, DetectionJobProgressView view) {
        synchronized (subscriber) {
            if (subscriber.closed) {
                return;
            }
            String state = view.getStatus() + ":" + view.getProgress() + ":" + view.getErrorCode();
            Instant now = clock.instant();
            try {
                if (!state.equals(subscriber.lastState)) {
                    SseEmitter.SseEventBuilder event = SseEmitter.event()
                            .name(eventName(view.getStatus()))
                            .data(toEvent(view), MediaType.APPLICATION_JSON);
                    if (subscriber.lastState == null) {
                        event.reconnectTime(settings.reconnectDelay().toMillis());
                    }
                    subscriber.emitter.send(event);
                    subscriber.lastState = state;
                    subscriber.lastSentAt = now;
                } else if (!now.isBefore(subscriber.lastSentAt.plus(settings.heartbeatInterval()))) {
                    subscriber.emitter.send(SseEmitter.event().comment("heartbeat"));
                    subscriber.lastSentAt = now;
                }
            } catch (IOException | IllegalStateException exception) {
                // The client disconnected or the response is no longer usable.
                LOG.debug("Progress stream for job {} ended: {}", subscriber.jobId, exception.getClass().getSimpleName());
                close(subscriber);
                return;
            }
            if (TERMINAL.contains(view.getStatus())) {
                close(subscriber);
            }
        }
    }

    static DetectionProgressEvent toEvent(DetectionJobProgressView view) {
        String message = view.getStatus() == DetectionJobStatus.FAILED && view.getErrorMessage() != null
                ? view.getErrorMessage() : DetectionJobQueryService.describe(view.getStatus());
        return new DetectionProgressEvent(view.getId(), view.getStatus(), view.getProgress(), message,
                view.getErrorCode(), view.getUpdatedAt());
    }

    static String eventName(DetectionJobStatus status) {
        return switch (status) {
            case COMPLETED -> COMPLETED_EVENT;
            case FAILED -> FAILED_EVENT;
            case CANCELLED -> CANCELLED_EVENT;
            default -> PROGRESS_EVENT;
        };
    }

    /** Completes the response and frees the slot; safe to call more than once. */
    private void close(Subscriber subscriber) {
        synchronized (subscriber) {
            if (!subscriber.closed) {
                subscriber.closed = true;
                try {
                    subscriber.emitter.complete();
                } catch (RuntimeException exception) {
                    LOG.debug("Ignoring an error while completing a progress stream", exception);
                }
            }
        }
        release(subscriber);
    }

    private void release(Subscriber subscriber) {
        subscriber.closed = true;
        if (subscribers.remove(subscriber.id) != null) {
            open.decrementAndGet();
        }
    }

    // Lifecycle: one daemon thread polls for all streams; nothing runs per connection.

    @Override
    public void start() {
        long interval = settings.pollInterval().toMillis();
        ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "detection-progress-poller");
            thread.setDaemon(true);
            return thread;
        });
        executor.scheduleWithFixedDelay(this::pollSafely, interval, interval, TimeUnit.MILLISECONDS);
        poller = executor;
    }

    private void pollSafely() {
        try {
            poll();
        } catch (RuntimeException exception) {
            // Database unavailable: keep the streams and try again on the next tick.
            LOG.warn("Progress stream poll failed: {}", exception.getClass().getSimpleName());
        }
    }

    @Override
    @PreDestroy
    public void stop() {
        ScheduledExecutorService executor = poller;
        poller = null;
        if (executor != null) {
            executor.shutdownNow();
        }
        List.copyOf(subscribers.values()).forEach(this::close);
    }

    @Override
    public boolean isRunning() {
        return poller != null;
    }

    private static final class Subscriber {
        private final UUID id;
        private final UUID jobId;
        private final SseEmitter emitter;
        private volatile boolean closed;
        private String lastState;
        private Instant lastSentAt = Instant.EPOCH;

        private Subscriber(UUID id, UUID jobId, SseEmitter emitter) {
            this.id = id;
            this.jobId = jobId;
            this.emitter = emitter;
        }
    }
}
