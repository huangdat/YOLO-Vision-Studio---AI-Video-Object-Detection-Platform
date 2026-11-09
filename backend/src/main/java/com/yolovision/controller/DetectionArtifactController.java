package com.yolovision.controller;

import com.yolovision.exception.ArtifactTransferException;
import com.yolovision.exception.RangeNotSatisfiableException;
import com.yolovision.service.ByteRange;
import com.yolovision.service.DetectionArtifact;
import com.yolovision.service.DetectionArtifactService;
import com.yolovision.service.DetectionArtifactService.ResolvedArtifact;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.enums.ParameterIn;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.CacheControl;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Artifacts of completed jobs, served from the private bucket through the backend: the browser
 * never receives storage URLs or credentials, and object keys come only from the database.
 * The video is streamed in bounded chunks with single-range support (see {@link ByteRange}).
 * Development-only until authentication, authorization, and rate limiting exist.
 */
@RestController
@RequestMapping("/api/v1/detections/{jobId}")
@Tag(name = "Detection artifacts", description = "Annotated video and result.json of completed jobs")
public class DetectionArtifactController {

    private static final Logger LOG = LoggerFactory.getLogger(DetectionArtifactController.class);
    private static final int BUFFER_BYTES = 64 * 1024;

    private final DetectionArtifactService artifacts;

    public DetectionArtifactController(DetectionArtifactService artifacts) {
        this.artifacts = artifacts;
    }

    @GetMapping("/video")
    @Operation(summary = "Stream the annotated MP4 inline (supports a single Range)")
    @Parameter(name = HttpHeaders.RANGE, in = ParameterIn.HEADER, description = "For example bytes=0-1023")
    @ApiResponse(responseCode = "200", description = "Complete video/mp4")
    @ApiResponse(responseCode = "206", description = "Requested byte range")
    @ApiResponse(responseCode = "404", description = "JOB_NOT_FOUND or ARTIFACT_NOT_FOUND")
    @ApiResponse(responseCode = "409", description = "RESULT_NOT_READY")
    @ApiResponse(responseCode = "416", description = "RANGE_NOT_SATISFIABLE")
    @ApiResponse(responseCode = "503", description = "STORAGE_UNAVAILABLE")
    public void video(@PathVariable UUID jobId, HttpServletRequest request, HttpServletResponse response)
            throws IOException {
        stream(jobId, false, request, response);
    }

    @GetMapping("/video/download")
    @Operation(summary = "Download the annotated MP4 as detection-<jobId>.mp4")
    @ApiResponse(responseCode = "404", description = "JOB_NOT_FOUND or ARTIFACT_NOT_FOUND")
    @ApiResponse(responseCode = "409", description = "RESULT_NOT_READY")
    @ApiResponse(responseCode = "503", description = "STORAGE_UNAVAILABLE")
    public void downloadVideo(@PathVariable UUID jobId, HttpServletRequest request, HttpServletResponse response)
            throws IOException {
        stream(jobId, true, request, response);
    }

    @GetMapping("/result.json")
    @Operation(summary = "The worker's original result.json (not the /result metadata DTO)")
    @ApiResponse(responseCode = "404", description = "JOB_NOT_FOUND or ARTIFACT_NOT_FOUND")
    @ApiResponse(responseCode = "409", description = "RESULT_NOT_READY")
    @ApiResponse(responseCode = "500", description = "ARTIFACT_INVALID")
    @ApiResponse(responseCode = "503", description = "STORAGE_UNAVAILABLE")
    public ResponseEntity<byte[]> resultJson(@PathVariable UUID jobId) {
        return json(jobId, false);
    }

    @GetMapping("/result.json/download")
    @Operation(summary = "Download the worker's result.json as detection-<jobId>-result.json")
    @ApiResponse(responseCode = "404", description = "JOB_NOT_FOUND or ARTIFACT_NOT_FOUND")
    @ApiResponse(responseCode = "409", description = "RESULT_NOT_READY")
    @ApiResponse(responseCode = "500", description = "ARTIFACT_INVALID")
    @ApiResponse(responseCode = "503", description = "STORAGE_UNAVAILABLE")
    public ResponseEntity<byte[]> downloadResultJson(@PathVariable UUID jobId) {
        return json(jobId, true);
    }

    private ResponseEntity<byte[]> json(UUID jobId, boolean attachment) {
        ResolvedArtifact artifact = artifacts.resolve(jobId, DetectionArtifact.RESULT_JSON);
        byte[] body = artifacts.readResultJson(artifact);
        return ResponseEntity.ok()
                .contentType(DetectionArtifact.RESULT_JSON.mediaType())
                .contentLength(body.length)
                .cacheControl(CacheControl.noStore())
                .header(HttpHeaders.CONTENT_DISPOSITION, disposition(artifact, attachment))
                .header("X-Content-Type-Options", "nosniff")
                .body(body);
    }

    private void stream(UUID jobId, boolean attachment, HttpServletRequest request, HttpServletResponse response)
            throws IOException {
        // Everything that can fail with a problem response happens before any header is set.
        ResolvedArtifact artifact = artifacts.resolve(jobId, DetectionArtifact.VIDEO);
        String etag = artifact.etag();
        ByteRange range = ByteRange.resolve(request.getHeader(HttpHeaders.RANGE),
                request.getHeader(HttpHeaders.IF_RANGE), etag, artifact.size());
        if (range instanceof ByteRange.Unsatisfiable) {
            throw new RangeNotSatisfiableException(artifact.size());
        }
        long offset = range instanceof ByteRange.Partial partial ? partial.start() : 0;
        long length = range instanceof ByteRange.Partial partial ? partial.length() : artifact.size();
        boolean head = "HEAD".equalsIgnoreCase(request.getMethod());
        InputStream in = head ? null : artifacts.open(artifact, offset, length);

        response.setStatus(range instanceof ByteRange.Partial ? HttpServletResponse.SC_PARTIAL_CONTENT
                : HttpServletResponse.SC_OK);
        response.setContentType(DetectionArtifact.VIDEO.mediaType().toString());
        response.setContentLengthLong(length);
        response.setHeader(HttpHeaders.ACCEPT_RANGES, "bytes");
        if (range instanceof ByteRange.Partial partial) {
            response.setHeader(HttpHeaders.CONTENT_RANGE, partial.contentRange());
        }
        if (etag != null) {
            response.setHeader(HttpHeaders.ETAG, etag);
        }
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION, disposition(artifact, attachment));
        response.setHeader(HttpHeaders.CACHE_CONTROL, CacheControl.noStore().getHeaderValue());
        response.setHeader("X-Content-Type-Options", "nosniff");
        if (in == null) {
            return;
        }
        try (in) {
            copy(in, response.getOutputStream(), length, jobId);
        }
    }

    /**
     * Copies exactly {@code length} bytes. A client disconnect ends the transfer quietly; a storage
     * failure after the response is committed is propagated so the connection is aborted.
     */
    private static void copy(InputStream in, OutputStream out, long length, UUID jobId) {
        byte[] buffer = new byte[BUFFER_BYTES];
        long remaining = length;
        while (remaining > 0) {
            int read;
            try {
                read = in.read(buffer, 0, (int) Math.min(buffer.length, remaining));
            } catch (IOException exception) {
                throw new ArtifactTransferException("Reading the video of job " + jobId + " from storage failed after "
                        + (length - remaining) + " of " + length + " bytes", exception);
            }
            if (read < 0) {
                throw new ArtifactTransferException("Storage ended the video of job " + jobId + " after "
                        + (length - remaining) + " of " + length + " bytes", null);
            }
            try {
                out.write(buffer, 0, read);
            } catch (IOException exception) {
                LOG.debug("Client disconnected from the video of job {} after {} of {} bytes", jobId,
                        length - remaining, length);
                return;
            }
            remaining -= read;
        }
        try {
            out.flush();
        } catch (IOException exception) {
            LOG.debug("Client disconnected from the video of job {} before the final flush", jobId);
        }
    }

    private static String disposition(ResolvedArtifact artifact, boolean attachment) {
        String filename = artifact.artifact().filename(artifact.jobId());
        return (attachment ? ContentDisposition.attachment() : ContentDisposition.inline())
                .filename(filename).build().toString();
    }
}
