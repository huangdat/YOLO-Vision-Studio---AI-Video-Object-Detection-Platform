package com.yolovision.service;

import com.yolovision.dto.messaging.DetectionEventMessage;
import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.exception.UnknownDetectionJobException;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.DetectionResultRepository;
import java.time.Instant;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * The only writer of job status. Every change locks the job row first, so duplicate or
 * concurrent events for one job are applied one at a time against the current state.
 *
 * <p>Rules: stages only move forward (PENDING, QUEUED, DOWNLOADING, DETECTING, ENCODING,
 * UPLOADING); progress never decreases and stays below 100 until completion; COMPLETED,
 * FAILED, and CANCELLED are terminal and are never overwritten.
 */
@Service
public class DetectionJobLifecycleService {

    public enum Outcome {
        /** The event changed the job. */
        APPLIED,
        /** Same stage and progress: only the activity lease was refreshed. */
        HEARTBEAT,
        /** An older stage than the job already reached; ignored. */
        STALE,
        /** The same terminal state was already recorded (duplicate delivery); ignored. */
        DUPLICATE,
        /** The job already ended differently; the event cannot change it. */
        IGNORED_TERMINAL,
        /** The completion contradicted the job (different model); the job was failed. */
        REJECTED
    }

    static final Set<DetectionJobStatus> TERMINAL = EnumSet.of(
            DetectionJobStatus.COMPLETED, DetectionJobStatus.FAILED, DetectionJobStatus.CANCELLED);
    static final Set<DetectionJobStatus> ACTIVE = EnumSet.of(DetectionJobStatus.DOWNLOADING,
            DetectionJobStatus.DETECTING, DetectionJobStatus.ENCODING, DetectionJobStatus.UPLOADING);

    private static final Logger LOG = LoggerFactory.getLogger(DetectionJobLifecycleService.class);
    private static final int MAX_ERROR_MESSAGE_LENGTH = 1000;

    private final DetectionJobRepository jobs;
    private final DetectionResultRepository results;

    public DetectionJobLifecycleService(DetectionJobRepository jobs, DetectionResultRepository results) {
        this.jobs = jobs;
        this.results = results;
    }

    /** Called after the broker confirmed the command; later stages are left untouched. */
    @Transactional
    public void markQueued(UUID jobId) {
        jobs.findByIdForUpdate(jobId).ifPresent(job -> {
            if (job.getStatus() == DetectionJobStatus.PENDING) {
                job.setStatus(DetectionJobStatus.QUEUED);
            }
        });
    }

    /** Fails a job that is not yet terminal, e.g. when its command can never be published. */
    @Transactional
    public boolean fail(UUID jobId, String code, String message) {
        DetectionJob job = jobs.findByIdForUpdate(jobId).orElse(null);
        if (job == null || TERMINAL.contains(job.getStatus())) {
            return false;
        }
        applyFailure(job, code, message);
        return true;
    }

    @Transactional
    public Outcome apply(DetectionEventMessage event) {
        DetectionJob job = jobs.findByIdForUpdate(event.jobId())
                .orElseThrow(() -> new UnknownDetectionJobException(event.jobId()));
        DetectionJobStatus current = job.getStatus();
        if (TERMINAL.contains(current)) {
            boolean duplicate = current.name().equals(event.status().name());
            return duplicate ? Outcome.DUPLICATE : Outcome.IGNORED_TERMINAL;
        }
        return switch (event.status()) {
            case COMPLETED -> complete(job, event);
            case FAILED -> {
                applyFailure(job, event.error().code(), event.error().message());
                yield Outcome.APPLIED;
            }
            default -> advance(job, DetectionJobStatus.valueOf(event.status().name()), event.progress());
        };
    }

    /** Fails non-terminal jobs whose worker went silent; returns the number failed. */
    @Transactional
    public int failStaleJobs(Instant processingCutoff, Instant queueCutoff, int limit) {
        int failed = 0;
        failed += failStale(List.copyOf(ACTIVE), processingCutoff, limit, "PROCESSING_TIMEOUT",
                "No progress was reported by a worker within the processing timeout.");
        failed += failStale(List.of(DetectionJobStatus.QUEUED), queueCutoff, limit, "QUEUE_TIMEOUT",
                "No worker started the job within the queue timeout.");
        return failed;
    }

    private int failStale(List<DetectionJobStatus> statuses, Instant cutoff, int limit, String code,
            String message) {
        int failed = 0;
        for (UUID id : jobs.findStaleJobIds(statuses, cutoff, PageRequest.of(0, limit))) {
            DetectionJob job = jobs.findByIdForUpdate(id).orElse(null);
            // Re-check under the lock: an event may have arrived since the query.
            if (job != null && statuses.contains(job.getStatus()) && job.getUpdatedAt().isBefore(cutoff)) {
                applyFailure(job, code, message);
                LOG.warn("Detection job {} failed by lease monitor: {}", id, code);
                failed++;
            }
        }
        return failed;
    }

    private Outcome advance(DetectionJob job, DetectionJobStatus stage, int reportedProgress) {
        if (stage.ordinal() < job.getStatus().ordinal()) {
            return Outcome.STALE;
        }
        // Intermediate events never claim completion.
        int progress = Math.max(job.getProgress(), Math.min(reportedProgress, 99));
        boolean changed = stage != job.getStatus() || progress != job.getProgress();
        if (job.getStartedAt() == null) {
            job.setStartedAt(Instant.now());
        }
        job.setStatus(stage);
        job.setProgress(progress);
        job.markActivity();
        return changed ? Outcome.APPLIED : Outcome.HEARTBEAT;
    }

    private Outcome complete(DetectionJob job, DetectionEventMessage event) {
        String expectedModel = job.getModel().getModelKey();
        if (!expectedModel.equals(event.modelKey())) {
            LOG.error("Completion for job {} reported model {} but the job requested {}",
                    job.getId(), event.modelKey(), expectedModel);
            applyFailure(job, "MODEL_MISMATCH",
                    "The worker reported a different model than the job requested.");
            return Outcome.REJECTED;
        }
        DetectionEventMessage.Result payload = event.result();
        if (!results.existsByJob_Id(job.getId())) {
            DetectionResult result = new DetectionResult(job, payload.outputVideoKey(),
                    Map.copyOf(payload.detectionSummary()));
            result.setResultJsonKey(payload.resultJsonKey());
            result.setTotalFrames(payload.totalFrames());
            result.setProcessingTimeMs(payload.processingTimeMs());
            results.save(result);
        }
        Instant now = Instant.now();
        if (job.getStartedAt() == null) {
            job.setStartedAt(now);
        }
        job.setStatus(DetectionJobStatus.COMPLETED);
        job.setProgress(100);
        job.setCompletedAt(now);
        job.setErrorCode(null);
        job.setErrorMessage(null);
        job.markActivity();
        LOG.info("Detection job {} completed: {} frames, output {}", job.getId(),
                payload.totalFrames(), payload.outputVideoKey());
        return Outcome.APPLIED;
    }

    private static void applyFailure(DetectionJob job, String code, String message) {
        job.setStatus(DetectionJobStatus.FAILED);
        job.setErrorCode(code);
        job.setErrorMessage(sanitize(message));
        job.setCompletedAt(Instant.now());
        job.markActivity();
    }

    /** Strips control characters and bounds length; the worker already removes paths and secrets. */
    static String sanitize(String message) {
        if (message == null || message.isBlank()) {
            return null;
        }
        String clean = message.replaceAll("[\\p{Cntrl}&&[^\\n]]", " ").strip();
        return clean.length() <= MAX_ERROR_MESSAGE_LENGTH ? clean : clean.substring(0, MAX_ERROR_MESSAGE_LENGTH);
    }
}
