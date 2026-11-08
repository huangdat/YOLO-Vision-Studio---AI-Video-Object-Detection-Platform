package com.yolovision.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.yolovision.config.MessagingProperties;
import com.yolovision.entity.DetectionJobOutboxMessage;
import com.yolovision.messaging.CommandPublicationException;
import com.yolovision.messaging.DetectionCommandPublisher;
import com.yolovision.repository.DetectionJobOutboxRepository;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.domain.Pageable;

class DetectionOutboxServiceTest {

    private DetectionJobOutboxRepository outbox;
    private DetectionCommandPublisher publisher;
    private DetectionJobLifecycleService lifecycle;
    private DetectionOutboxService service;
    private DetectionJobOutboxMessage message;

    @BeforeEach
    void setUp() {
        outbox = mock(DetectionJobOutboxRepository.class);
        publisher = mock(DetectionCommandPublisher.class);
        lifecycle = mock(DetectionJobLifecycleService.class);
        MessagingProperties properties = new MessagingProperties("c", "q", "k", "e", "eq", "ek", "d", "dq", "dk", 5,
                new MessagingProperties.Outbox(true, Duration.ofSeconds(1), 20, 3, Duration.ofSeconds(2),
                        Duration.ofSeconds(5), Duration.ofSeconds(1)),
                new MessagingProperties.Jobs(false, Duration.ofMinutes(1), Duration.ofMinutes(30), Duration.ofDays(1)));
        service = new DetectionOutboxService(outbox, publisher, lifecycle, properties);
        message = new DetectionJobOutboxMessage(UUID.randomUUID(), UUID.randomUUID(), "detection.execute.v1",
                JsonNodeFactory.instance.objectNode());
        when(outbox.lockDue(eq(DetectionJobOutboxMessage.Status.PENDING), any(Instant.class), any(Pageable.class)))
                .thenReturn(List.of(message));
    }

    @Test
    void confirmedPublicationMarksTheRowPublishedAndTheJobQueued() throws Exception {
        assertThat(service.publishDueBatch()).isEqualTo(1);

        verify(publisher).publish(message);
        assertThat(message.getStatus()).isEqualTo(DetectionJobOutboxMessage.Status.PUBLISHED);
        assertThat(message.getPublishedAt()).isNotNull();
        verify(lifecycle).markQueued(message.getJobId());
    }

    @Test
    void failedPublicationStaysPendingWithBackoffAndDoesNotQueueTheJob() throws Exception {
        doThrow(new CommandPublicationException("broker down")).when(publisher).publish(message);
        Instant before = Instant.now();

        service.publishDueBatch();

        assertThat(message.getStatus()).isEqualTo(DetectionJobOutboxMessage.Status.PENDING);
        assertThat(message.getAttempts()).isEqualTo(1);
        assertThat(message.getLastError()).isEqualTo("broker down");
        assertThat(message.getNextAttemptAt()).isAfterOrEqualTo(before.plusSeconds(2));
        verify(lifecycle, never()).markQueued(any());
        verify(lifecycle, never()).fail(any(), any(), any());
    }

    @Test
    void exhaustedRetriesFailTheRowAndTheJobInsteadOfRetryingForever() throws Exception {
        doThrow(new CommandPublicationException("broker down")).when(publisher).publish(message);

        service.publishDueBatch();
        service.publishDueBatch();
        service.publishDueBatch();

        assertThat(message.getStatus()).isEqualTo(DetectionJobOutboxMessage.Status.FAILED);
        assertThat(message.getAttempts()).isEqualTo(3);
        verify(lifecycle).fail(eq(message.getJobId()), eq("PUBLICATION_FAILED"), any());
    }

    @Test
    void backoffIsExponentialAndCapped() {
        assertThat(service.backoff(1)).isEqualTo(Duration.ofSeconds(2));
        assertThat(service.backoff(2)).isEqualTo(Duration.ofSeconds(4));
        assertThat(service.backoff(3)).isEqualTo(Duration.ofSeconds(5));
        assertThat(service.backoff(60)).isEqualTo(Duration.ofSeconds(5));
    }
}
