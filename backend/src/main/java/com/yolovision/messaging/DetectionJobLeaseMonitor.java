package com.yolovision.messaging;

import com.yolovision.config.MessagingProperties;
import com.yolovision.service.DetectionJobLifecycleService;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Activity lease: workers send heartbeat events while a job runs, refreshing the job's
 * updated_at. Jobs that go silent (worker crash, lost events) are failed instead of
 * remaining in an intermediate state forever.
 */
@Component
@ConditionalOnProperty(prefix = "app.messaging.jobs", name = "lease-monitor-enabled", havingValue = "true")
public class DetectionJobLeaseMonitor {

    private static final Logger LOG = LoggerFactory.getLogger(DetectionJobLeaseMonitor.class);
    private static final int BATCH = 100;

    private final DetectionJobLifecycleService lifecycle;
    private final MessagingProperties.Jobs settings;

    public DetectionJobLeaseMonitor(DetectionJobLifecycleService lifecycle, MessagingProperties messaging) {
        this.lifecycle = lifecycle;
        this.settings = messaging.jobs();
    }

    @Scheduled(fixedDelayString = "${app.messaging.jobs.lease-check-interval}")
    public void failExpiredJobs() {
        try {
            Instant now = Instant.now();
            int failed = lifecycle.failStaleJobs(now.minus(settings.processingTimeout()),
                    now.minus(settings.queueTimeout()), BATCH);
            if (failed > 0) {
                LOG.warn("Lease monitor failed {} silent detection job(s)", failed);
            }
        } catch (RuntimeException exception) {
            LOG.warn("Lease monitor check failed: {}", exception.getClass().getSimpleName());
        }
    }
}
