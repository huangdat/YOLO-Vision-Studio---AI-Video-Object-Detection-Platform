package com.yolovision.service;

import com.yolovision.dto.DetectionResultMetadataResponse;
import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.exception.DetectionJobNotFoundException;
import com.yolovision.exception.DetectionResultInconsistentException;
import com.yolovision.exception.DetectionResultNotReadyException;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.DetectionResultRepository;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Result metadata exactly as persisted by the Phase 05 completion handling; never invented. */
@Service
@Transactional(readOnly = true)
public class DetectionResultQueryService {

    private static final Logger LOG = LoggerFactory.getLogger(DetectionResultQueryService.class);

    private final DetectionJobRepository jobs;
    private final DetectionResultRepository results;

    public DetectionResultQueryService(DetectionJobRepository jobs, DetectionResultRepository results) {
        this.jobs = jobs;
        this.results = results;
    }

    public DetectionResultMetadataResponse getResult(UUID jobId) {
        DetectionJob job = jobs.findWithModelById(jobId).orElseThrow(DetectionJobNotFoundException::new);
        if (job.getStatus() != DetectionJobStatus.COMPLETED) {
            throw new DetectionResultNotReadyException(job.getStatus());
        }
        DetectionResult result = results.findByJob_Id(jobId).orElseThrow(() -> {
            LOG.error("Detection job {} is COMPLETED but has no result row", jobId);
            return new DetectionResultInconsistentException(jobId);
        });
        Map<String, Long> summary = result.getDetectionSummary() == null ? Map.of() : result.getDetectionSummary();
        long total = summary.values().stream().mapToLong(Long::longValue).sum();
        return new DetectionResultMetadataResponse(job.getId(), job.getStatus(), job.getModel().getModelKey(),
                job.getModel().getVersion(), result.getTotalFrames(), total, result.getProcessingTimeMs(), summary,
                DetectionResultMetadataResponse.FRAME_DETECTIONS, hasText(result.getOutputVideoKey()),
                hasText(result.getResultJsonKey()), result.getCreatedAt(), job.getCompletedAt());
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }
}
