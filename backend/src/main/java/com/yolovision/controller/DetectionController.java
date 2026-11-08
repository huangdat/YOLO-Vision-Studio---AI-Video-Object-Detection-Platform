package com.yolovision.controller;

import com.yolovision.dto.CreateDetectionRequest;
import com.yolovision.dto.DetectionJobAcceptedResponse;
import com.yolovision.dto.DetectionJobDetailsResponse;
import com.yolovision.dto.DetectionJobListFilter;
import com.yolovision.dto.DetectionJobSummaryResponse;
import com.yolovision.dto.DetectionResultMetadataResponse;
import com.yolovision.dto.PageResponse;
import com.yolovision.service.DetectionJobQueryService;
import com.yolovision.service.DetectionProgressStreamService;
import com.yolovision.service.DetectionResultQueryService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import java.net.URI;
import java.util.UUID;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * Detection jobs. Submission is asynchronous (202): inference runs in the Python worker via
 * the Phase 05 outbox and RabbitMQ. Controllers never change job status.
 * Development-only until authentication exists; keep the backend bound to localhost.
 */
@RestController
@RequestMapping("/api/v1/detections")
@Tag(name = "Detections", description = "Asynchronous YOLO detection jobs")
public class DetectionController {

    private final DetectionJobQueryService jobService;
    private final DetectionResultQueryService resultService;
    private final DetectionProgressStreamService streamService;

    public DetectionController(DetectionJobQueryService jobService, DetectionResultQueryService resultService,
            DetectionProgressStreamService streamService) {
        this.jobService = jobService;
        this.resultService = resultService;
        this.streamService = streamService;
    }

    @PostMapping(consumes = MediaType.APPLICATION_JSON_VALUE)
    @Operation(summary = "Submit a YouTube video for asynchronous detection")
    @ApiResponse(responseCode = "202", description = "Accepted; follow the Location header")
    @ApiResponse(responseCode = "400", description = "INVALID_DETECTION_REQUEST or MALFORMED_REQUEST")
    @ApiResponse(responseCode = "404", description = "MODEL_NOT_FOUND")
    @ApiResponse(responseCode = "409", description = "MODEL_DISABLED or MODEL_NOT_SUPPORTED")
    @ApiResponse(responseCode = "413", description = "PAYLOAD_TOO_LARGE")
    @ApiResponse(responseCode = "503", description = "SERVICE_UNAVAILABLE; nothing was accepted")
    public ResponseEntity<DetectionJobAcceptedResponse> create(
            @RequestBody(required = false) CreateDetectionRequest request) {
        DetectionJobAcceptedResponse accepted = jobService.create(request);
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .location(URI.create("/api/v1/detections/" + accepted.jobId()))
                .body(accepted);
    }

    @GetMapping
    @Operation(summary = "List detection jobs, newest first")
    public PageResponse<DetectionJobSummaryResponse> list(@Valid @ModelAttribute DetectionJobListFilter filter) {
        return jobService.listJobs(filter);
    }

    @GetMapping("/{jobId}")
    @Operation(summary = "Get the persisted state of one job")
    @ApiResponse(responseCode = "404", description = "JOB_NOT_FOUND")
    public DetectionJobDetailsResponse get(@PathVariable UUID jobId) {
        return jobService.getJob(jobId);
    }

    @GetMapping("/{jobId}/result")
    @Operation(summary = "Get result metadata of a completed job")
    @ApiResponse(responseCode = "404", description = "JOB_NOT_FOUND")
    @ApiResponse(responseCode = "409", description = "RESULT_NOT_READY")
    public DetectionResultMetadataResponse result(@PathVariable UUID jobId) {
        return resultService.getResult(jobId);
    }

    @GetMapping(path = "/{jobId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @Operation(summary = "Stream job progress as Server-Sent Events",
            description = "Events: detection.progress, detection.completed, detection.failed, detection.cancelled. "
                    + "Sends the current snapshot first; closes after a terminal state.")
    @ApiResponse(responseCode = "404", description = "JOB_NOT_FOUND")
    @ApiResponse(responseCode = "503", description = "STREAM_CAPACITY_EXCEEDED")
    public ResponseEntity<SseEmitter> events(@PathVariable UUID jobId) {
        SseEmitter emitter = streamService.subscribe(jobId);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                // Ask reverse proxies such as nginx not to buffer the stream.
                .header("X-Accel-Buffering", "no")
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(emitter);
    }
}
