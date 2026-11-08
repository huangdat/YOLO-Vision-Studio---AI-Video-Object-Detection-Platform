package com.yolovision.config;

import com.yolovision.dto.DetectionJobSubmissionRequest;
import com.yolovision.entity.DetectionSourceType;
import com.yolovision.service.DetectionJobSubmissionService;
import java.math.BigDecimal;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/**
 * Development-only way to submit one job through the real submission service before the
 * Phase 06 REST API exists. Active only with the explicit {@code dev-harness} profile; it
 * never enables a model, so the chosen model must already be enabled by an administrator.
 *
 * <pre>
 * SPRING_PROFILES_ACTIVE=dev-harness HARNESS_MODEL_KEY=yolo11n HARNESS_SOURCE_TYPE=LOCAL_FILE \
 * HARNESS_SOURCE=clip.mp4 HARNESS_IMAGE_SIZE=320 java -jar backend.jar
 * </pre>
 */
@Component
@Profile("dev-harness")
public class DevelopmentJobHarness implements ApplicationRunner {

    private static final Logger LOG = LoggerFactory.getLogger(DevelopmentJobHarness.class);

    private final DetectionJobSubmissionService submissions;
    private final Environment environment;

    public DevelopmentJobHarness(DetectionJobSubmissionService submissions, Environment environment) {
        this.submissions = submissions;
        this.environment = environment;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        String confidence = environment.getProperty("HARNESS_CONFIDENCE");
        String imageSize = environment.getProperty("HARNESS_IMAGE_SIZE");
        DetectionJobSubmissionRequest request = new DetectionJobSubmissionRequest(
                environment.getRequiredProperty("HARNESS_MODEL_KEY"),
                DetectionSourceType.valueOf(environment.getProperty("HARNESS_SOURCE_TYPE", "LOCAL_FILE")),
                environment.getRequiredProperty("HARNESS_SOURCE"),
                confidence == null ? null : new BigDecimal(confidence),
                imageSize == null ? null : Integer.valueOf(imageSize),
                null);
        UUID jobId = submissions.submit(request);
        LOG.info("DEV HARNESS submitted detection job {}", jobId);
    }
}
