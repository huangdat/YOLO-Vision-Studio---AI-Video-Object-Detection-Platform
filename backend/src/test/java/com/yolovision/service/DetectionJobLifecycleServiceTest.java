package com.yolovision.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.yolovision.dto.messaging.DetectionEventMessage;
import com.yolovision.dto.messaging.DetectionEventStatus;
import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.entity.ModelConfig;
import com.yolovision.exception.UnknownDetectionJobException;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.DetectionResultRepository;
import com.yolovision.repository.ModelConfigRepository;
import com.yolovision.service.DetectionJobLifecycleService.Outcome;
import jakarta.persistence.EntityManager;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@ActiveProfiles("test")
@Transactional
class DetectionJobLifecycleServiceTest {

    @Autowired
    private DetectionJobLifecycleService lifecycle;

    @Autowired
    private ModelConfigRepository models;

    @Autowired
    private DetectionJobRepository jobs;

    @Autowired
    private DetectionResultRepository results;

    @Autowired
    private EntityManager entityManager;

    @Autowired
    private JdbcTemplate jdbc;

    private UUID jobId;

    @BeforeEach
    void createQueuedJob() {
        ModelConfig model = models.findByModelKey("yolo11n").orElseGet(() -> {
            ModelConfig created = new ModelConfig("yolo11n", "YOLO11", "n", "DETECT", "yolo11n.pt");
            created.setEnabled(true);
            return models.save(created);
        });
        DetectionJob job = new DetectionJob(model, "clip.mp4", new BigDecimal("0.250"), 320, List.of(2, 5));
        jobs.saveAndFlush(job);
        jobId = job.getId();
        lifecycle.markQueued(jobId);
    }

    @Test
    void publicationConfirmMovesPendingToQueuedOnly() {
        assertThat(job().getStatus()).isEqualTo(DetectionJobStatus.QUEUED);
        lifecycle.apply(progress(DetectionEventStatus.DETECTING, 40));

        lifecycle.markQueued(jobId);

        assertThat(job().getStatus()).isEqualTo(DetectionJobStatus.DETECTING);
    }

    @Test
    void progressEventsAdvanceStageProgressAndStartTime() {
        assertThat(lifecycle.apply(progress(DetectionEventStatus.DOWNLOADING, 10))).isEqualTo(Outcome.APPLIED);
        assertThat(lifecycle.apply(progress(DetectionEventStatus.DETECTING, 65))).isEqualTo(Outcome.APPLIED);

        DetectionJob job = job();
        assertThat(job.getStatus()).isEqualTo(DetectionJobStatus.DETECTING);
        assertThat(job.getProgress()).isEqualTo(65);
        assertThat(job.getStartedAt()).isNotNull();
        assertThat(job.getCompletedAt()).isNull();
    }

    @Test
    void outOfOrderOlderStageIsIgnored() {
        lifecycle.apply(progress(DetectionEventStatus.ENCODING, 90));

        assertThat(lifecycle.apply(progress(DetectionEventStatus.DETECTING, 70))).isEqualTo(Outcome.STALE);

        assertThat(job().getStatus()).isEqualTo(DetectionJobStatus.ENCODING);
        assertThat(job().getProgress()).isEqualTo(90);
    }

    @Test
    void progressNeverDecreasesWithinAStage() {
        lifecycle.apply(progress(DetectionEventStatus.DETECTING, 60));
        lifecycle.apply(progress(DetectionEventStatus.DETECTING, 40));

        assertThat(job().getProgress()).isEqualTo(60);
    }

    @Test
    void intermediateEventsNeverReportOneHundredPercent() {
        lifecycle.apply(progress(DetectionEventStatus.UPLOADING, 100));

        assertThat(job().getStatus()).isEqualTo(DetectionJobStatus.UPLOADING);
        assertThat(job().getProgress()).isEqualTo(99);
    }

    @Test
    void duplicateProgressIsAHeartbeatThatRefreshesTheLease() {
        lifecycle.apply(progress(DetectionEventStatus.DETECTING, 50));
        setUpdatedAt(Instant.now().minus(Duration.ofHours(1)));

        assertThat(lifecycle.apply(progress(DetectionEventStatus.DETECTING, 50))).isEqualTo(Outcome.HEARTBEAT);
        entityManager.flush();
        entityManager.clear();

        assertThat(job().getUpdatedAt()).isAfter(Instant.now().minus(Duration.ofMinutes(1)));
    }

    @Test
    void completionPersistsResultMetadataAndCompletesTheJob() {
        lifecycle.apply(progress(DetectionEventStatus.UPLOADING, 97));

        assertThat(lifecycle.apply(completed("yolo11n"))).isEqualTo(Outcome.APPLIED);
        entityManager.flush();
        entityManager.clear();

        DetectionJob job = job();
        assertThat(job.getStatus()).isEqualTo(DetectionJobStatus.COMPLETED);
        assertThat(job.getProgress()).isEqualTo(100);
        assertThat(job.getCompletedAt()).isNotNull();
        DetectionResult result = results.findByJob_Id(jobId).orElseThrow();
        assertThat(result.getOutputVideoKey()).isEqualTo("detections/" + jobId + "/detected.mp4");
        assertThat(result.getResultJsonKey()).isEqualTo("detections/" + jobId + "/result.json");
        assertThat(result.getTotalFrames()).isEqualTo(36);
        assertThat(result.getProcessingTimeMs()).isEqualTo(7058L);
        assertThat(result.getDetectionSummary()).containsExactlyInAnyOrderEntriesOf(Map.of("bus", 36L, "car", 4L));
    }

    @Test
    void duplicateCompletionDoesNotCreateASecondResult() {
        lifecycle.apply(completed("yolo11n"));

        assertThat(lifecycle.apply(completed("yolo11n"))).isEqualTo(Outcome.DUPLICATE);
        entityManager.flush();

        assertThat(jdbc.queryForObject("SELECT count(*) FROM detection_results WHERE job_id = ?",
                Long.class, jobId)).isEqualTo(1L);
    }

    @Test
    void lateProgressCannotMoveACompletedJobBackward() {
        lifecycle.apply(completed("yolo11n"));

        assertThat(lifecycle.apply(progress(DetectionEventStatus.DETECTING, 70)))
                .isEqualTo(Outcome.IGNORED_TERMINAL);

        assertThat(job().getStatus()).isEqualTo(DetectionJobStatus.COMPLETED);
        assertThat(job().getProgress()).isEqualTo(100);
    }

    @Test
    void completionWithADifferentModelFailsTheJobWithoutAResult() {
        assertThat(lifecycle.apply(completed("yolov8n"))).isEqualTo(Outcome.REJECTED);

        assertThat(job().getStatus()).isEqualTo(DetectionJobStatus.FAILED);
        assertThat(job().getErrorCode()).isEqualTo("MODEL_MISMATCH");
        assertThat(results.existsByJob_Id(jobId)).isFalse();
    }

    @Test
    void failureEventRecordsSanitizedCodeAndMessage() {
        lifecycle.apply(progress(DetectionEventStatus.DETECTING, 30));

        assertThat(lifecycle.apply(failed("VIDEO_DOWNLOAD_FAILED", "Download failed\u0000 after retries")))
                .isEqualTo(Outcome.APPLIED);

        DetectionJob job = job();
        assertThat(job.getStatus()).isEqualTo(DetectionJobStatus.FAILED);
        assertThat(job.getErrorCode()).isEqualTo("VIDEO_DOWNLOAD_FAILED");
        assertThat(job.getErrorMessage()).isEqualTo("Download failed  after retries");
        assertThat(job.getProgress()).isEqualTo(30);
        assertThat(job.getCompletedAt()).isNotNull();
    }

    @Test
    void failedJobsIgnoreLateCompletionAndDuplicateFailures() {
        lifecycle.apply(failed("INFERENCE_FAILED", "Inference failed"));

        assertThat(lifecycle.apply(failed("INFERENCE_FAILED", "Inference failed"))).isEqualTo(Outcome.DUPLICATE);
        assertThat(lifecycle.apply(completed("yolo11n"))).isEqualTo(Outcome.IGNORED_TERMINAL);

        assertThat(job().getStatus()).isEqualTo(DetectionJobStatus.FAILED);
        assertThat(results.existsByJob_Id(jobId)).isFalse();
    }

    @Test
    void cancelledJobsAreNeverOverwritten() {
        jdbc.update("UPDATE detection_jobs SET status = 'CANCELLED' WHERE id = ?", jobId);
        entityManager.clear();

        assertThat(lifecycle.apply(progress(DetectionEventStatus.DETECTING, 10))).isEqualTo(Outcome.IGNORED_TERMINAL);
        assertThat(lifecycle.apply(completed("yolo11n"))).isEqualTo(Outcome.IGNORED_TERMINAL);
        assertThat(lifecycle.fail(jobId, "X", "y")).isFalse();

        assertThat(job().getStatus()).isEqualTo(DetectionJobStatus.CANCELLED);
    }

    @Test
    void unknownJobIsReported() {
        DetectionEventMessage event = new DetectionEventMessage(1, UUID.randomUUID(), UUID.randomUUID(),
                DetectionEventStatus.DETECTING, 5, null, null, null, Instant.now(), null, null, null);

        assertThatThrownBy(() -> lifecycle.apply(event)).isInstanceOf(UnknownDetectionJobException.class);
    }

    @Test
    void leaseMonitorFailsSilentActiveJobsButNotRecentOnes() {
        lifecycle.apply(progress(DetectionEventStatus.DETECTING, 20));
        entityManager.flush();
        Instant now = Instant.now();

        assertThat(lifecycle.failStaleJobs(now.minus(Duration.ofMinutes(30)), now.minus(Duration.ofDays(1)), 10))
                .isZero();

        setUpdatedAt(now.minus(Duration.ofHours(1)));
        assertThat(lifecycle.failStaleJobs(now.minus(Duration.ofMinutes(30)), now.minus(Duration.ofDays(1)), 10))
                .isEqualTo(1);
        assertThat(job().getStatus()).isEqualTo(DetectionJobStatus.FAILED);
        assertThat(job().getErrorCode()).isEqualTo("PROCESSING_TIMEOUT");
    }

    @Test
    void leaseMonitorUsesTheLongerQueueTimeoutForQueuedJobs() {
        Instant now = Instant.now();
        setUpdatedAt(now.minus(Duration.ofHours(2)));

        assertThat(lifecycle.failStaleJobs(now.minus(Duration.ofMinutes(30)), now.minus(Duration.ofDays(1)), 10))
                .isZero();
        assertThat(lifecycle.failStaleJobs(now.minus(Duration.ofMinutes(30)), now.minus(Duration.ofHours(1)), 10))
                .isEqualTo(1);
        assertThat(job().getErrorCode()).isEqualTo("QUEUE_TIMEOUT");
    }

    private DetectionJob job() {
        entityManager.flush();
        entityManager.clear();
        return jobs.findById(jobId).orElseThrow();
    }

    private void setUpdatedAt(Instant instant) {
        entityManager.flush();
        jdbc.update("UPDATE detection_jobs SET updated_at = ? WHERE id = ?", Timestamp.from(instant), jobId);
        entityManager.clear();
    }

    private DetectionEventMessage progress(DetectionEventStatus status, int progress) {
        return new DetectionEventMessage(1, UUID.randomUUID(), jobId, status, progress, 10, 36,
                "Processing", Instant.now(), null, null, null);
    }

    private DetectionEventMessage completed(String modelKey) {
        return new DetectionEventMessage(1, UUID.randomUUID(), jobId, DetectionEventStatus.COMPLETED, 100, 36, 36,
                "Completed", Instant.now(), modelKey, new DetectionEventMessage.Result(
                        "detections/" + jobId + "/detected.mp4", "detections/" + jobId + "/result.json",
                        36, 7058L, Map.of("bus", 36L, "car", 4L)), null);
    }

    private DetectionEventMessage failed(String code, String message) {
        return new DetectionEventMessage(1, UUID.randomUUID(), jobId, DetectionEventStatus.FAILED, 30, null, null,
                null, Instant.now(), null, null, new DetectionEventMessage.Error(code, message, false));
    }
}
