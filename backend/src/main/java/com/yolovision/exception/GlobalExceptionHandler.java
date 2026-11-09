package com.yolovision.exception;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.TypeMismatchException;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.lang.Nullable;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/**
 * RFC 9457 problem details for every API error. Each body carries a stable application
 * {@code code} and a {@code timestamp}; validation errors add an {@code errors} field map.
 * Internal messages, SQL details, paths, and stack traces are never returned.
 */
@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    private static final Logger LOG = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(
            MethodArgumentNotValidException exception,
            HttpHeaders headers,
            HttpStatusCode status,
            WebRequest request) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(status, "Request validation failed.");
        Map<String, String> errors = new LinkedHashMap<>();
        exception.getBindingResult().getFieldErrors().forEach(error -> errors.putIfAbsent(error.getField(),
                error.isBindingFailure() ? "has an invalid value" : error.getDefaultMessage()));
        problem.setProperty("errors", errors);
        return handleExceptionInternal(exception, problem, headers, status, request);
    }

    @Override
    protected ResponseEntity<Object> handleTypeMismatch(TypeMismatchException exception, HttpHeaders headers,
            HttpStatusCode status, WebRequest request) {
        String name = exception instanceof MethodArgumentTypeMismatchException mismatch
                ? mismatch.getName() : exception.getPropertyName();
        String expected = UUID.class.equals(exception.getRequiredType()) ? "must be a valid UUID"
                : "has an invalid value";
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(status,
                "Parameter '" + name + "' " + expected + ".");
        return handleExceptionInternal(exception, problem, headers, status, request);
    }

    @Override
    protected ResponseEntity<Object> handleHttpMessageNotReadable(HttpMessageNotReadableException exception,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        // Jackson messages can echo input; return a fixed explanation instead.
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(status,
                "The request body is missing, malformed, too large, or contains unsupported fields.");
        return handleExceptionInternal(exception, problem, headers, status, request);
    }

    /** Adds code and timestamp to every problem produced by Spring MVC's own handling. */
    @Override
    protected ResponseEntity<Object> handleExceptionInternal(Exception exception, @Nullable Object body,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        ResponseEntity<Object> response = super.handleExceptionInternal(exception, body, headers, status, request);
        if (response != null && response.getBody() instanceof ProblemDetail problem) {
            enrich(problem, frameworkCode(exception, status));
        }
        return response;
    }

    @ExceptionHandler(DetectionModelUnavailableException.class)
    public ResponseEntity<ProblemDetail> handleModelUnavailable(DetectionModelUnavailableException exception) {
        return switch (exception.getReason()) {
            case NOT_FOUND -> problem(HttpStatus.NOT_FOUND, "MODEL_NOT_FOUND",
                    "The requested model is not registered.", exception.getErrors());
            case DISABLED -> problem(HttpStatus.CONFLICT, "MODEL_DISABLED",
                    "The requested model is not enabled for detection.", exception.getErrors());
            case NOT_DETECTION -> problem(HttpStatus.CONFLICT, "MODEL_NOT_SUPPORTED",
                    "The requested model is not an object detection model.", exception.getErrors());
        };
    }

    @ExceptionHandler(InvalidDetectionJobException.class)
    public ResponseEntity<ProblemDetail> handleInvalidDetection(InvalidDetectionJobException exception) {
        return problem(HttpStatus.BAD_REQUEST, "INVALID_DETECTION_REQUEST", "Detection request validation failed.",
                exception.getErrors());
    }

    @ExceptionHandler(ModelNotFoundException.class)
    public ResponseEntity<ProblemDetail> handleModelNotFound(ModelNotFoundException exception) {
        ResponseEntity<ProblemDetail> response = problem(HttpStatus.NOT_FOUND, "MODEL_NOT_FOUND",
                exception.getMessage(), null);
        response.getBody().setTitle("Model not found");
        return response;
    }

    @ExceptionHandler(DetectionJobNotFoundException.class)
    public ResponseEntity<ProblemDetail> handleJobNotFound(DetectionJobNotFoundException exception) {
        ResponseEntity<ProblemDetail> response = problem(HttpStatus.NOT_FOUND, "JOB_NOT_FOUND",
                exception.getMessage(), null);
        response.getBody().setTitle("Detection job not found");
        return response;
    }

    @ExceptionHandler(DetectionResultNotReadyException.class)
    public ResponseEntity<ProblemDetail> handleResultNotReady(DetectionResultNotReadyException exception) {
        ResponseEntity<ProblemDetail> response = problem(HttpStatus.CONFLICT, "RESULT_NOT_READY",
                exception.getMessage(), null);
        response.getBody().setProperty("jobStatus", exception.getStatus());
        return response;
    }

    @ExceptionHandler(DetectionResultInconsistentException.class)
    public ResponseEntity<ProblemDetail> handleResultInconsistent(DetectionResultInconsistentException exception) {
        LOG.error("Result consistency error: {}", exception.getMessage());
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, "RESULT_UNAVAILABLE",
                "The job is completed but its result metadata is unavailable.", null);
    }

    @ExceptionHandler(ArtifactNotFoundException.class)
    public ResponseEntity<ProblemDetail> handleArtifactNotFound(ArtifactNotFoundException exception) {
        // The internal reason is logged by the artifact service and never returned.
        ResponseEntity<ProblemDetail> response = problem(HttpStatus.NOT_FOUND, "ARTIFACT_NOT_FOUND",
                "The requested artifact is not available for this job.", null);
        response.getBody().setTitle("Artifact not available");
        return response;
    }

    @ExceptionHandler(ArtifactInvalidException.class)
    public ResponseEntity<ProblemDetail> handleArtifactInvalid(ArtifactInvalidException exception) {
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, "ARTIFACT_INVALID",
                "The stored artifact cannot be served.", null);
    }

    @ExceptionHandler(StorageUnavailableException.class)
    public ResponseEntity<ProblemDetail> handleStorageUnavailable(StorageUnavailableException exception) {
        ResponseEntity<ProblemDetail> response = problem(HttpStatus.SERVICE_UNAVAILABLE, "STORAGE_UNAVAILABLE",
                exception.getMessage(), null);
        return ResponseEntity.status(response.getStatusCode()).header(HttpHeaders.RETRY_AFTER, "10")
                .body(response.getBody());
    }

    @ExceptionHandler(RangeNotSatisfiableException.class)
    public ResponseEntity<ProblemDetail> handleRangeNotSatisfiable(RangeNotSatisfiableException exception) {
        ResponseEntity<ProblemDetail> response = problem(HttpStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                "RANGE_NOT_SATISFIABLE", exception.getMessage(), null);
        return ResponseEntity.status(response.getStatusCode())
                .header(HttpHeaders.CONTENT_RANGE, "bytes */" + exception.getSize())
                .header(HttpHeaders.ACCEPT_RANGES, "bytes")
                .body(response.getBody());
    }

    /**
     * The response is already committed, so no problem body can be written. Rethrowing lets the
     * servlet container abort the connection; the client then sees an incomplete transfer.
     */
    @ExceptionHandler(ArtifactTransferException.class)
    public void handleArtifactTransfer(ArtifactTransferException exception) {
        LOG.warn("Artifact transfer aborted: {}", exception.getMessage());
        throw exception;
    }

    @ExceptionHandler(StreamCapacityExceededException.class)
    public ResponseEntity<ProblemDetail> handleStreamCapacity(StreamCapacityExceededException exception) {
        ResponseEntity<ProblemDetail> response = problem(HttpStatus.SERVICE_UNAVAILABLE, "STREAM_CAPACITY_EXCEEDED",
                exception.getMessage(), null);
        return ResponseEntity.status(response.getStatusCode()).header(HttpHeaders.RETRY_AFTER, "10")
                .body(response.getBody());
    }

    @ExceptionHandler(DataAccessException.class)
    public ResponseEntity<ProblemDetail> handleDataAccessFailure(DataAccessException exception) {
        LOG.error("Database access failed while serving an API request", exception);
        return problem(HttpStatus.SERVICE_UNAVAILABLE, "SERVICE_UNAVAILABLE",
                "The data store is temporarily unavailable.", null);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ProblemDetail> handleUnexpectedException(Exception exception) {
        LOG.error("Unhandled API exception", exception);
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "An unexpected error occurred.", null);
    }

    private static ResponseEntity<ProblemDetail> problem(HttpStatus status, String code, String detail,
            @Nullable Map<String, String> errors) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(status, detail);
        if (errors != null && !errors.isEmpty()) {
            problem.setProperty("errors", errors);
        }
        enrich(problem, code);
        return ResponseEntity.status(status).body(problem);
    }

    private static void enrich(ProblemDetail problem, String code) {
        Map<String, Object> properties = problem.getProperties();
        if (properties == null || !properties.containsKey("code")) {
            problem.setProperty("code", code);
        }
        problem.setProperty("timestamp", Instant.now().toString());
    }

    private static String frameworkCode(Exception exception, HttpStatusCode status) {
        if (exception instanceof MethodArgumentNotValidException) {
            return "VALIDATION_FAILED";
        }
        if (exception instanceof TypeMismatchException) {
            return "INVALID_PARAMETER";
        }
        if (exception instanceof HttpMessageNotReadableException) {
            return "MALFORMED_REQUEST";
        }
        if (exception instanceof HttpRequestMethodNotSupportedException) {
            return "METHOD_NOT_ALLOWED";
        }
        if (exception instanceof HttpMediaTypeNotSupportedException) {
            return "UNSUPPORTED_MEDIA_TYPE";
        }
        if (exception instanceof NoResourceFoundException) {
            return "NOT_FOUND";
        }
        HttpStatus resolved = HttpStatus.resolve(status.value());
        return resolved == null ? "HTTP_" + status.value() : resolved.name();
    }
}
