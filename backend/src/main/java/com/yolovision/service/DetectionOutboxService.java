package com.yolovision.service;

import com.yolovision.config.MessagingProperties;
import com.yolovision.entity.DetectionJobOutboxMessage;
import com.yolovision.messaging.CommandPublicationException;
import com.yolovision.messaging.DetectionCommandPublisher;
import com.yolovision.repository.DetectionJobOutboxRepository;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Publishes due outbox rows. Delivery is at least once: if the database commit fails
 * after a confirmed publish, the row is published again and the worker deduplicates by
 * job id. Attempts are bounded with exponential backoff; an exhausted row fails its job.
 */
@Service
public class DetectionOutboxService {

    private static final Logger LOG = LoggerFactory.getLogger(DetectionOutboxService.class);

    private final DetectionJobOutboxRepository outbox;
    private final DetectionCommandPublisher publisher;
    private final DetectionJobLifecycleService lifecycle;
    private final MessagingProperties.Outbox settings;

    public DetectionOutboxService(DetectionJobOutboxRepository outbox, DetectionCommandPublisher publisher,
            DetectionJobLifecycleService lifecycle, MessagingProperties messaging) {
        this.outbox = outbox;
        this.publisher = publisher;
        this.lifecycle = lifecycle;
        this.settings = messaging.outbox();
    }

    /** Publishes one batch of due rows; returns how many rows were attempted. */
    @Transactional
    public int publishDueBatch() {
        Instant now = Instant.now();
        List<DetectionJobOutboxMessage> due = outbox.lockDue(
                DetectionJobOutboxMessage.Status.PENDING, now, PageRequest.of(0, settings.batchSize()));
        for (DetectionJobOutboxMessage message : due) {
            try {
                publisher.publish(message);
                message.markPublished(Instant.now());
                lifecycle.markQueued(message.getJobId());
                LOG.info("Published command {} for detection job {} (attempt {})",
                        message.getId(), message.getJobId(), message.getAttempts() + 1);
            } catch (CommandPublicationException exception) {
                recordFailure(message, exception, now);
            }
        }
        return due.size();
    }

    private void recordFailure(DetectionJobOutboxMessage message, CommandPublicationException exception,
            Instant now) {
        Duration delay = backoff(message.getAttempts() + 1);
        boolean exhausted = message.recordFailure(exception.getMessage(), now.plus(delay), settings.maxAttempts());
        if (exhausted) {
            LOG.error("Command {} for detection job {} failed after {} attempts: {}", message.getId(),
                    message.getJobId(), message.getAttempts(), exception.getMessage());
            lifecycle.fail(message.getJobId(), "PUBLICATION_FAILED",
                    "The job could not be delivered to the processing queue.");
        } else {
            LOG.warn("Command {} for detection job {} not published (attempt {}/{}), retry in {}: {}",
                    message.getId(), message.getJobId(), message.getAttempts(), settings.maxAttempts(), delay,
                    exception.getMessage());
        }
    }

    Duration backoff(int attempt) {
        long factor = 1L << Math.min(Math.max(attempt - 1, 0), 20);
        Duration delay = settings.initialBackoff().multipliedBy(factor);
        return delay.compareTo(settings.maxBackoff()) > 0 ? settings.maxBackoff() : delay;
    }
}
