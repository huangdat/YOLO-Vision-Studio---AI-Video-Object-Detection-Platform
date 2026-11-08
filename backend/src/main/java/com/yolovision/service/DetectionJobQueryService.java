package com.yolovision.service;

import com.yolovision.dto.CreateDetectionRequest;
import com.yolovision.dto.DetectionJobAcceptedResponse;
import com.yolovision.dto.DetectionJobDetailsResponse;
import com.yolovision.dto.DetectionJobListFilter;
import com.yolovision.dto.DetectionJobSubmissionRequest;
import com.yolovision.dto.DetectionJobSummaryResponse;
import com.yolovision.dto.PageResponse;
import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionSourceType;
import com.yolovision.exception.DetectionJobNotFoundException;
import com.yolovision.exception.DetectionModelUnavailableException;
import com.yolovision.exception.InvalidDetectionJobException;
import com.yolovision.repository.DetectionJobRepository;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * REST-facing job operations. Creation delegates to the Phase 05 submission service (and
 * therefore the transactional outbox); queries are read-only. Status is never modified here.
 */
@Service
@Transactional(readOnly = true)
public class DetectionJobQueryService {

    /** Newest first, with the id as a stable tie-breaker for equal timestamps. */
    static final Sort HISTORY_ORDER = Sort.by(Sort.Order.desc("createdAt"), Sort.Order.desc("id"));

    private final DetectionJobSubmissionService submissions;
    private final DetectionJobRepository jobs;

    public DetectionJobQueryService(DetectionJobSubmissionService submissions, DetectionJobRepository jobs) {
        this.submissions = submissions;
        this.jobs = jobs;
    }

    /**
     * Accepts a public YouTube job. Submission and the response read share one transaction:
     * a client receives 202 only for a committed job, and a failure before commit leaves
     * neither a job nor an outbox message behind.
     */
    @Transactional
    public DetectionJobAcceptedResponse create(CreateDetectionRequest request) {
        if (request == null) {
            throw InvalidDetectionJobException.of("request", "a JSON request body is required");
        }
        UUID jobId;
        try {
            jobId = submissions.submit(new DetectionJobSubmissionRequest(request.modelKey(),
                    DetectionSourceType.YOUTUBE_URL, request.videoUrl(), request.confidence(), request.imageSize(),
                    request.classes()));
        } catch (DetectionModelUnavailableException exception) {
            throw exception;
        } catch (InvalidDetectionJobException exception) {
            throw new InvalidDetectionJobException(publicFieldNames(exception.getErrors()));
        }
        DetectionJob job = jobs.findWithModelById(jobId).orElseThrow(DetectionJobNotFoundException::new);
        return new DetectionJobAcceptedResponse(job.getId(), job.getStatus(), job.getProgress(),
                job.getModel().getModelKey(), "Detection job accepted");
    }

    public DetectionJobDetailsResponse getJob(UUID jobId) {
        return toDetails(jobs.findWithModelById(jobId).orElseThrow(DetectionJobNotFoundException::new));
    }

    public PageResponse<DetectionJobSummaryResponse> listJobs(DetectionJobListFilter filter) {
        List<Specification<DetectionJob>> criteria = new ArrayList<>();
        if (filter.status() != null) {
            criteria.add(DetectionJobRepository.hasStatus(filter.status()));
        }
        if (filter.modelKey() != null) {
            criteria.add(DetectionJobRepository.hasModelKey(filter.modelKey()));
        }
        PageRequest page = PageRequest.of(filter.pageOrDefault(), filter.sizeOrDefault(), HISTORY_ORDER);
        return PageResponse.of(jobs.findAll(Specification.allOf(criteria), page).map(DetectionJobQueryService::toSummary));
    }

    static DetectionJobDetailsResponse toDetails(DetectionJob job) {
        boolean youtube = job.getSourceType() == DetectionSourceType.YOUTUBE_URL;
        return new DetectionJobDetailsResponse(job.getId(), job.getModel().getModelKey(),
                job.getModel().getVersion(), job.getSourceType(), youtube ? job.getVideoUrl() : null,
                job.getStatus(), job.getProgress(), job.getConfidence(), job.getImageSize(),
                job.getSelectedClasses(), job.getCreatedAt(), job.getStartedAt(), job.getCompletedAt(),
                job.getUpdatedAt(), job.getErrorCode(), job.getErrorMessage());
    }

    static DetectionJobSummaryResponse toSummary(DetectionJob job) {
        return new DetectionJobSummaryResponse(job.getId(), job.getModel().getModelKey(), job.getStatus(),
                job.getProgress(), job.getCreatedAt(), job.getCompletedAt(), job.getErrorCode());
    }

    /** Short user-facing description of a status; never claims progress that is not stored. */
    public static String describe(DetectionJobStatus status) {
        return switch (status) {
            case PENDING -> "Detection job accepted";
            case QUEUED -> "Waiting for a detection worker";
            case DOWNLOADING -> "Downloading the video";
            case DETECTING -> "Detecting objects in video frames";
            case ENCODING -> "Encoding the annotated video";
            case UPLOADING -> "Storing the results";
            case COMPLETED -> "Detection completed";
            case FAILED -> "Detection failed";
            case CANCELLED -> "Detection job cancelled";
        };
    }

    /** The internal request names the URL "source"; the public contract calls it "videoUrl". */
    private static Map<String, String> publicFieldNames(Map<String, String> errors) {
        Map<String, String> renamed = new LinkedHashMap<>();
        errors.forEach((field, message) -> {
            if (!field.equals("sourceType")) {
                renamed.putIfAbsent(field.equals("source") ? "videoUrl" : field, message);
            }
        });
        return renamed;
    }
}
