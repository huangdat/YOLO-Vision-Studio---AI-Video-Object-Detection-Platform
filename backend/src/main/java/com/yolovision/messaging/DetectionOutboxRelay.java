package com.yolovision.messaging;

import com.yolovision.config.MessagingProperties;
import com.yolovision.service.DetectionOutboxService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** Polls the outbox and publishes due commands; safe to run on several backend instances. */
@Component
@ConditionalOnProperty(prefix = "app.messaging.outbox", name = "enabled", havingValue = "true")
public class DetectionOutboxRelay {

    private static final Logger LOG = LoggerFactory.getLogger(DetectionOutboxRelay.class);

    private final DetectionOutboxService outboxService;
    private final int batchSize;

    public DetectionOutboxRelay(DetectionOutboxService outboxService, MessagingProperties messaging) {
        this.outboxService = outboxService;
        this.batchSize = messaging.outbox().batchSize();
    }

    @Scheduled(fixedDelayString = "${app.messaging.outbox.poll-interval}")
    public void relay() {
        try {
            int attempted;
            do {
                attempted = outboxService.publishDueBatch();
            } while (attempted == batchSize);
        } catch (RuntimeException exception) {
            // Database unavailable: rows stay pending and are retried on the next poll.
            LOG.warn("Outbox relay poll failed: {}", exception.getClass().getSimpleName());
        }
    }
}
