package com.yolovision.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.yolovision.config.DetectionStreamProperties;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.exception.DetectionJobNotFoundException;
import com.yolovision.exception.StreamCapacityExceededException;
import com.yolovision.repository.DetectionJobProgressView;
import com.yolovision.repository.DetectionJobRepository;
import java.io.IOException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/** Deterministic: a manual clock, explicit poll() calls, and recording emitters; no sleeps. */
class DetectionProgressStreamServiceTest {

    record Row(UUID getId, DetectionJobStatus getStatus, int getProgress, String getErrorCode,
            String getErrorMessage, Instant getUpdatedAt) implements DetectionJobProgressView {
    }

    static final class ManualClock extends Clock {
        Instant now = Instant.parse("2026-11-08T09:00:00Z");

        @Override
        public ZoneOffset getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(java.time.ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now;
        }
    }

    static final class RecordingEmitter extends SseEmitter {
        final List<String> events = new ArrayList<>();
        final Long timeout;
        boolean completed;
        IOException failure;
        Runnable timeoutCallback;
        Runnable completionCallback;
        Consumer<Throwable> errorCallback;

        RecordingEmitter(Long timeout) {
            super(timeout);
            this.timeout = timeout;
        }

        @Override
        public void send(SseEventBuilder builder) throws IOException {
            if (failure != null) {
                throw failure;
            }
            StringBuilder text = new StringBuilder();
            for (ResponseBodyEmitter.DataWithMediaType part : builder.build()) {
                text.append(part.getData());
            }
            events.add(text.toString());
        }

        @Override
        public void complete() {
            completed = true;
            if (completionCallback != null) {
                completionCallback.run(); // the container invokes this after completion
            }
        }

        @Override
        public void onTimeout(Runnable callback) {
            timeoutCallback = callback;
        }

        @Override
        public void onCompletion(Runnable callback) {
            completionCallback = callback;
        }

        @Override
        public void onError(Consumer<Throwable> callback) {
            errorCallback = callback;
        }

        List<String> named(String eventName) {
            return events.stream().filter(event -> event.contains("event:" + eventName + "\n")).toList();
        }

        long heartbeats() {
            return events.stream().filter(event -> event.startsWith(":heartbeat")).count();
        }
    }

    private final Map<UUID, Row> table = new ConcurrentHashMap<>();
    private final List<RecordingEmitter> emitters = new ArrayList<>();
    private final ManualClock clock = new ManualClock();
    private DetectionJobRepository jobs;
    private DetectionProgressStreamService service;

    @BeforeEach
    void setUp() {
        jobs = mock(DetectionJobRepository.class);
        when(jobs.findProgressByIdIn(any())).thenAnswer(invocation -> {
            Collection<UUID> ids = invocation.getArgument(0);
            return ids.stream().map(table::get).filter(java.util.Objects::nonNull).toList();
        });
        service = service(3);
    }

    private DetectionProgressStreamService service(int maxConnections) {
        DetectionStreamProperties properties = new DetectionStreamProperties(Duration.ofMinutes(30),
                Duration.ofSeconds(1), Duration.ofSeconds(15), maxConnections, Duration.ofSeconds(3));
        return new DetectionProgressStreamService(jobs, properties, clock, timeout -> {
            RecordingEmitter emitter = new RecordingEmitter(timeout);
            emitters.add(emitter);
            return emitter;
        });
    }

    private UUID job(DetectionJobStatus status, int progress) {
        UUID id = UUID.randomUUID();
        set(id, status, progress, null, null);
        return id;
    }

    private void set(UUID id, DetectionJobStatus status, int progress, String code, String message) {
        table.put(id, new Row(id, status, progress, code, message, clock.now));
    }

    private RecordingEmitter subscribe(UUID id) {
        service.subscribe(id);
        return emitters.get(emitters.size() - 1);
    }

    @Test
    void sendsAnImmediateSnapshotWithReconnectHintAndTimeout() {
        UUID id = job(DetectionJobStatus.QUEUED, 0);

        RecordingEmitter emitter = subscribe(id);

        assertThat(emitter.timeout).isEqualTo(Duration.ofMinutes(30).toMillis());
        assertThat(emitter.events).hasSize(1);
        assertThat(emitter.events.get(0)).contains("event:detection.progress", "retry:3000", "status=QUEUED",
                "progress=0", "message=Waiting for a detection worker");
        assertThat(service.openStreams()).isEqualTo(1);
    }

    @Test
    void sendsUpdatesOnlyWhenStatusOrProgressChanges() {
        UUID id = job(DetectionJobStatus.QUEUED, 0);
        RecordingEmitter emitter = subscribe(id);

        service.poll();
        service.poll();
        set(id, DetectionJobStatus.DETECTING, 40, null, null);
        service.poll();
        service.poll();
        set(id, DetectionJobStatus.DETECTING, 65, null, null);
        service.poll();

        assertThat(emitter.named("detection.progress")).hasSize(3);
        assertThat(emitter.events.get(1)).contains("status=DETECTING", "progress=40");
        assertThat(emitter.events.get(2)).contains("progress=65");
        assertThat(emitter.events.get(2)).doesNotContain("retry:");
    }

    @Test
    void sendsHeartbeatCommentsOnlyAfterTheIntervalWithoutChanges() {
        UUID id = job(DetectionJobStatus.DETECTING, 10);
        RecordingEmitter emitter = subscribe(id);

        clock.now = clock.now.plusSeconds(14);
        service.poll();
        assertThat(emitter.heartbeats()).isZero();
        clock.now = clock.now.plusSeconds(1);
        service.poll();
        assertThat(emitter.heartbeats()).isEqualTo(1);
        service.poll();
        assertThat(emitter.heartbeats()).isEqualTo(1);
    }

    @Test
    void completionIsSentOnceAndTheStreamIsClosedAndReleased() {
        UUID id = job(DetectionJobStatus.UPLOADING, 96);
        RecordingEmitter emitter = subscribe(id);

        set(id, DetectionJobStatus.COMPLETED, 100, null, null);
        service.poll();
        service.poll();

        assertThat(emitter.named("detection.completed")).hasSize(1);
        assertThat(emitter.named("detection.completed").get(0)).contains("status=COMPLETED", "progress=100");
        assertThat(emitter.completed).isTrue();
        assertThat(service.openStreams()).isZero();
    }

    @Test
    void failureEventCarriesTheStoredErrorCodeAndMessage() {
        UUID id = job(DetectionJobStatus.DOWNLOADING, 5);
        RecordingEmitter emitter = subscribe(id);

        set(id, DetectionJobStatus.FAILED, 5, "VIDEO_DOWNLOAD_FAILED", "The YouTube video could not be downloaded.");
        service.poll();

        assertThat(emitter.named("detection.failed")).singleElement().asString()
                .contains("errorCode=VIDEO_DOWNLOAD_FAILED", "message=The YouTube video could not be downloaded.");
        assertThat(emitter.completed).isTrue();
        assertThat(service.openStreams()).isZero();
    }

    @Test
    void cancelledJobsCloseWithACancelledEvent() {
        UUID id = job(DetectionJobStatus.CANCELLED, 20);

        RecordingEmitter emitter = subscribe(id);

        assertThat(emitter.named("detection.cancelled")).hasSize(1);
        assertThat(emitter.completed).isTrue();
    }

    @Test
    void alreadyTerminalJobsReceiveOneEventAndNoSlotIsHeld() {
        UUID id = job(DetectionJobStatus.COMPLETED, 100);

        RecordingEmitter emitter = subscribe(id);

        assertThat(emitter.events).hasSize(1);
        assertThat(emitter.completed).isTrue();
        assertThat(service.openStreams()).isZero();
    }

    @Test
    void clientDisconnectDuringSendCleansUp() {
        UUID id = job(DetectionJobStatus.DETECTING, 10);
        RecordingEmitter emitter = subscribe(id);

        emitter.failure = new IOException("Broken pipe");
        set(id, DetectionJobStatus.DETECTING, 50, null, null);
        service.poll();

        assertThat(emitter.completed).isTrue();
        assertThat(service.openStreams()).isZero();
        service.poll(); // nothing left to poll
        verify(jobs, times(2)).findProgressByIdIn(any());
    }

    @Test
    void containerErrorCallbackReleasesTheSlot() {
        RecordingEmitter emitter = subscribe(job(DetectionJobStatus.DETECTING, 10));

        emitter.errorCallback.accept(new IOException("connection reset"));

        assertThat(service.openStreams()).isZero();
    }

    @Test
    void timeoutCompletesTheStreamAndReleasesTheSlot() {
        RecordingEmitter emitter = subscribe(job(DetectionJobStatus.DETECTING, 10));

        emitter.timeoutCallback.run();

        assertThat(emitter.completed).isTrue();
        assertThat(service.openStreams()).isZero();
    }

    @Test
    void reconnectingClientReceivesTheLatestSnapshotImmediately() {
        UUID id = job(DetectionJobStatus.DETECTING, 20);
        RecordingEmitter first = subscribe(id);
        first.timeoutCallback.run();

        set(id, DetectionJobStatus.ENCODING, 88, null, null);
        RecordingEmitter second = subscribe(id);

        assertThat(second.events).hasSize(1);
        assertThat(second.events.get(0)).contains("status=ENCODING", "progress=88");
    }

    @Test
    void unknownJobIsRejectedWithoutReservingASlot() {
        assertThatThrownBy(() -> service.subscribe(UUID.randomUUID()))
                .isInstanceOf(DetectionJobNotFoundException.class);
        assertThat(service.openStreams()).isZero();
        assertThat(emitters).isEmpty();
    }

    @Test
    void multipleListenersShareOneQueryPerPollAndEachReceiveUpdates() {
        UUID first = job(DetectionJobStatus.QUEUED, 0);
        UUID second = job(DetectionJobStatus.QUEUED, 0);
        RecordingEmitter a = subscribe(first);
        RecordingEmitter b = subscribe(first);
        RecordingEmitter c = subscribe(second);

        set(first, DetectionJobStatus.DETECTING, 30, null, null);
        service.poll();

        verify(jobs, times(4)).findProgressByIdIn(any()); // 3 subscriptions + 1 poll
        assertThat(a.events).hasSize(2);
        assertThat(b.events).hasSize(2);
        assertThat(c.events).hasSize(1);
    }

    @Test
    void connectionLimitIsEnforcedAndFreedSlotsCanBeReused() {
        RecordingEmitter first = subscribe(job(DetectionJobStatus.QUEUED, 0));
        subscribe(job(DetectionJobStatus.QUEUED, 0));
        subscribe(job(DetectionJobStatus.QUEUED, 0));
        UUID waiting = job(DetectionJobStatus.QUEUED, 0);

        assertThatThrownBy(() -> service.subscribe(waiting)).isInstanceOf(StreamCapacityExceededException.class);
        assertThat(service.openStreams()).isEqualTo(3);

        first.timeoutCallback.run();
        service.subscribe(waiting);
        assertThat(service.openStreams()).isEqualTo(3);
    }

    @Test
    void deletedJobClosesItsStreams() {
        UUID id = job(DetectionJobStatus.QUEUED, 0);
        RecordingEmitter emitter = subscribe(id);

        table.remove(id);
        service.poll();

        assertThat(emitter.completed).isTrue();
        assertThat(service.openStreams()).isZero();
    }

    @Test
    void databaseFailureDuringPollKeepsStreamsOpen() {
        UUID id = job(DetectionJobStatus.QUEUED, 0);
        RecordingEmitter emitter = subscribe(id);
        org.mockito.Mockito.doThrow(new org.springframework.dao.QueryTimeoutException("slow"))
                .when(jobs).findProgressByIdIn(any());

        assertThatThrownBy(() -> service.poll()).isInstanceOf(org.springframework.dao.QueryTimeoutException.class);
        assertThat(emitter.completed).isFalse();
        assertThat(service.openStreams()).isEqualTo(1);
    }

    @Test
    void shutdownClosesEveryStream() {
        RecordingEmitter a = subscribe(job(DetectionJobStatus.QUEUED, 0));
        RecordingEmitter b = subscribe(job(DetectionJobStatus.DETECTING, 5));

        service.stop();

        assertThat(a.completed).isTrue();
        assertThat(b.completed).isTrue();
        assertThat(service.openStreams()).isZero();
    }

    @Test
    void pollWithoutSubscribersDoesNotQueryTheDatabase() {
        service.poll();

        verify(jobs, times(0)).findProgressByIdIn(any());
    }
}
