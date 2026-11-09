package com.yolovision.service;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.exception.ArtifactInvalidException;
import com.yolovision.exception.ArtifactNotFoundException;
import com.yolovision.exception.DetectionJobNotFoundException;
import com.yolovision.exception.DetectionResultInconsistentException;
import com.yolovision.exception.DetectionResultNotReadyException;
import com.yolovision.exception.StorageObjectNotFoundException;
import com.yolovision.exception.StorageUnavailableException;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.DetectionResultRepository;
import com.yolovision.storage.ObjectStorage;
import com.yolovision.storage.StoredObject;
import java.io.IOException;
import java.io.InputStream;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Resolves and opens the artifacts of completed jobs. Object keys come only from the job's
 * {@link DetectionResult} row and must name that job's own artifact; clients never supply keys,
 * buckets, or paths. Every check, including the storage stat, happens before a response is
 * committed, so failures are still reported as problem details.
 */
@Service
public class DetectionArtifactService {

    /** result.json is a small manifest; anything larger is not served (and never buffered). */
    public static final int MAX_RESULT_JSON_BYTES = 2 * 1024 * 1024;

    private static final Logger LOG = LoggerFactory.getLogger(DetectionArtifactService.class);
    private static final Pattern SAFE_KEY = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9/_.-]{0,1023}$");
    private static final Pattern SENSITIVE_FIELD = Pattern.compile(
            "(?i).*(password|secret|token|credential|access[_-]?key|private[_-]?key).*");
    private static final Pattern ABSOLUTE_PATH = Pattern.compile("^(?:/(?!/)|[A-Za-z]:[\\\\/]|\\\\\\\\).*", Pattern.DOTALL);

    private final DetectionJobRepository jobs;
    private final DetectionResultRepository results;
    private final ObjectStorage storage;
    private final ObjectMapper objectMapper;

    public DetectionArtifactService(DetectionJobRepository jobs, DetectionResultRepository results,
            ObjectStorage storage, ObjectMapper objectMapper) {
        this.jobs = jobs;
        this.results = results;
        this.storage = storage;
        this.objectMapper = objectMapper;
    }

    /** An approved, existing, non-empty artifact of one completed job. */
    public record ResolvedArtifact(UUID jobId, DetectionArtifact artifact, StoredObject object) {

        public long size() {
            return object.size();
        }

        /** Strong validator for If-Range, quoted as HTTP requires; null when storage reported none. */
        public String etag() {
            String etag = object.etag();
            return etag == null || etag.isBlank() ? null : "\"" + etag.replace("\"", "") + "\"";
        }
    }

    @Transactional(readOnly = true)
    public ResolvedArtifact resolve(UUID jobId, DetectionArtifact artifact) {
        DetectionJob job = jobs.findById(jobId).orElseThrow(DetectionJobNotFoundException::new);
        if (job.getStatus() != DetectionJobStatus.COMPLETED) {
            throw new DetectionResultNotReadyException(job.getStatus());
        }
        DetectionResult result = results.findByJob_Id(jobId).orElseThrow(() -> {
            LOG.error("Detection job {} is COMPLETED but has no result row", jobId);
            return new DetectionResultInconsistentException(jobId);
        });
        String key = artifact == DetectionArtifact.VIDEO ? result.getOutputVideoKey() : result.getResultJsonKey();
        if (key == null || key.isBlank()) {
            throw missing(jobId, artifact, "no object key is recorded");
        }
        if (!belongsToJob(key, jobId, artifact)) {
            throw missing(jobId, artifact, "the recorded key does not name this job's artifact");
        }
        StoredObject object;
        try {
            object = storage.stat(key);
        } catch (StorageObjectNotFoundException exception) {
            throw missing(jobId, artifact, "the referenced object is missing from storage");
        }
        if (object.size() <= 0) {
            throw missing(jobId, artifact, "the stored object is empty");
        }
        if (object.contentType() != null && !object.contentType().isBlank()
                && !artifact.mediaType().isCompatibleWith(safeType(object.contentType()))) {
            // The response type is fixed per artifact; a mismatch is only logged.
            LOG.warn("Artifact {} of job {} is stored as {}; serving it as {}", artifact, jobId,
                    object.contentType(), artifact.mediaType());
        }
        return new ResolvedArtifact(jobId, artifact, object);
    }

    /** Opens exactly {@code length} bytes from {@code offset}; the caller closes the stream. */
    public InputStream open(ResolvedArtifact artifact, long offset, long length) {
        try {
            return storage.open(artifact.object().key(), offset, length);
        } catch (StorageObjectNotFoundException exception) {
            throw missing(artifact.jobId(), artifact.artifact(), "the object disappeared before it was opened");
        }
    }

    /**
     * The stored result.json bytes, unchanged, after checking that they are bounded, valid UTF-8
     * JSON describing this job, and free of path- or credential-like content.
     */
    public byte[] readResultJson(ResolvedArtifact artifact) {
        if (artifact.artifact() != DetectionArtifact.RESULT_JSON) {
            throw new IllegalArgumentException("Not a result.json artifact");
        }
        if (artifact.size() > MAX_RESULT_JSON_BYTES) {
            throw invalid(artifact.jobId(), "result.json exceeds " + MAX_RESULT_JSON_BYTES + " bytes");
        }
        byte[] bytes;
        try (InputStream in = open(artifact, 0, artifact.size())) {
            bytes = in.readNBytes(MAX_RESULT_JSON_BYTES + 1);
        } catch (IOException exception) {
            LOG.warn("Reading result.json of job {} failed: {}", artifact.jobId(), exception.getClass().getSimpleName());
            throw new StorageUnavailableException(exception);
        }
        if (bytes.length != artifact.size()) {
            throw invalid(artifact.jobId(), "result.json length differs from the stored size");
        }
        JsonNode root;
        try {
            String text = StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(bytes)).toString();
            root = objectMapper.reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(text);
        } catch (CharacterCodingException exception) {
            throw invalid(artifact.jobId(), "result.json is not valid UTF-8");
        } catch (IOException exception) {
            throw invalid(artifact.jobId(), "result.json is not valid JSON");
        }
        if (root == null || !root.isObject()) {
            throw invalid(artifact.jobId(), "result.json is not a JSON object");
        }
        JsonNode jobId = root.get("jobId");
        if (jobId != null && !artifact.jobId().toString().equalsIgnoreCase(jobId.asText())) {
            throw invalid(artifact.jobId(), "result.json describes a different job");
        }
        String unsafe = findUnsafeContent(root, "$");
        if (unsafe != null) {
            throw invalid(artifact.jobId(), "result.json contains path- or credential-like content at " + unsafe);
        }
        return bytes;
    }

    static boolean belongsToJob(String key, UUID jobId, DetectionArtifact artifact) {
        return SAFE_KEY.matcher(key).matches()
                && !key.contains("..") && !key.contains("//")
                && key.endsWith("/" + jobId + "/" + artifact.objectName());
    }

    private static String findUnsafeContent(JsonNode node, String location) {
        if (node.isObject()) {
            for (Iterator<Map.Entry<String, JsonNode>> fields = node.fields(); fields.hasNext();) {
                Map.Entry<String, JsonNode> field = fields.next();
                if (SENSITIVE_FIELD.matcher(field.getKey()).matches()) {
                    return location + "." + field.getKey();
                }
                String found = findUnsafeContent(field.getValue(), location + "." + field.getKey());
                if (found != null) {
                    return found;
                }
            }
        } else if (node.isArray()) {
            for (int index = 0; index < node.size(); index++) {
                String found = findUnsafeContent(node.get(index), location + "[" + index + "]");
                if (found != null) {
                    return found;
                }
            }
        } else if (node.isTextual() && ABSOLUTE_PATH.matcher(node.asText()).matches()) {
            return location;
        }
        return null;
    }

    private static org.springframework.http.MediaType safeType(String value) {
        try {
            return org.springframework.http.MediaType.parseMediaType(value);
        } catch (IllegalArgumentException exception) {
            return org.springframework.http.MediaType.APPLICATION_OCTET_STREAM;
        }
    }

    private static ArtifactNotFoundException missing(UUID jobId, DetectionArtifact artifact, String reason) {
        LOG.error("Artifact {} of completed job {} is unavailable: {}", artifact, jobId, reason);
        return new ArtifactNotFoundException(reason);
    }

    private static ArtifactInvalidException invalid(UUID jobId, String reason) {
        LOG.error("Result JSON of job {} cannot be served: {}", jobId, reason);
        return new ArtifactInvalidException(reason);
    }
}
