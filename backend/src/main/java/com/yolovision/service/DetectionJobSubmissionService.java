package com.yolovision.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yolovision.dto.DetectionJobSubmissionRequest;
import com.yolovision.dto.messaging.DetectionCommandMessage;
import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobOutboxMessage;
import com.yolovision.entity.DetectionSourceType;
import com.yolovision.entity.ModelConfig;
import com.yolovision.exception.InvalidDetectionJobException;
import com.yolovision.repository.DetectionJobOutboxRepository;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.ModelConfigRepository;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validator;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.net.URI;
import java.net.URISyntaxException;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Creates a detection job and its execution command atomically. The command is not
 * sent here: the outbox relay publishes it after commit, so a broker outage can delay
 * a job but cannot lose it, and a rollback can never leave a published orphan command.
 */
@Service
public class DetectionJobSubmissionService {

    static final BigDecimal DEFAULT_CONFIDENCE = new BigDecimal("0.250");
    static final int DEFAULT_IMAGE_SIZE = 960;
    /** COCO bicycle, car, motorcycle, bus, truck. */
    static final List<Integer> DEFAULT_CLASSES = List.of(1, 2, 3, 5, 7);

    private static final Logger LOG = LoggerFactory.getLogger(DetectionJobSubmissionService.class);
    private static final Set<String> YOUTUBE_HOSTS = Set.of(
            "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be");
    private static final Pattern LOCAL_PATH = Pattern.compile("^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$");

    private final ModelConfigRepository models;
    private final DetectionJobRepository jobs;
    private final DetectionJobOutboxRepository outbox;
    private final ObjectMapper objectMapper;
    private final Validator validator;

    public DetectionJobSubmissionService(ModelConfigRepository models, DetectionJobRepository jobs,
            DetectionJobOutboxRepository outbox, ObjectMapper objectMapper, Validator validator) {
        this.models = models;
        this.jobs = jobs;
        this.outbox = outbox;
        this.objectMapper = objectMapper;
        this.validator = validator;
    }

    @Transactional
    public UUID submit(DetectionJobSubmissionRequest request) {
        validate(request);
        ModelConfig model = models.findByModelKey(request.modelKey())
                .orElseThrow(() -> InvalidDetectionJobException.of("modelKey", "is not registered"));
        if (!"DETECT".equals(model.getTaskType())) {
            throw InvalidDetectionJobException.of("modelKey", "is not an object detection model");
        }
        // Administrative enablement only; worker cache readiness is verified by the worker.
        if (!model.isEnabled()) {
            throw InvalidDetectionJobException.of("modelKey", "is not enabled for detection");
        }
        BigDecimal confidence = request.confidence() == null
                ? DEFAULT_CONFIDENCE : request.confidence().setScale(3, RoundingMode.UNNECESSARY);
        int imageSize = request.imageSize() == null ? DEFAULT_IMAGE_SIZE : request.imageSize();
        List<Integer> classes = request.classes() == null ? DEFAULT_CLASSES : List.copyOf(request.classes());

        DetectionJob job = new DetectionJob(model, request.source().strip(), confidence, imageSize, classes);
        job.setSourceType(request.sourceType());
        jobs.saveAndFlush(job);

        DetectionCommandMessage command = new DetectionCommandMessage(
                DetectionCommandMessage.SCHEMA_VERSION, UUID.randomUUID(), job.getId(), model.getModelKey(),
                job.getSourceType(), job.getVideoUrl(), confidence, imageSize, classes, job.getCreatedAt());
        outbox.save(new DetectionJobOutboxMessage(command.messageId(), job.getId(),
                DetectionCommandMessage.MESSAGE_TYPE, serialize(command)));
        LOG.info("Detection job {} created with model {} (source type {}); command {} queued in outbox",
                job.getId(), model.getModelKey(), job.getSourceType(), command.messageId());
        return job.getId();
    }

    private void validate(DetectionJobSubmissionRequest request) {
        if (request == null) {
            throw InvalidDetectionJobException.of("request", "is required");
        }
        Map<String, String> errors = new LinkedHashMap<>();
        for (ConstraintViolation<DetectionJobSubmissionRequest> violation : validator.validate(request)) {
            errors.putIfAbsent(violation.getPropertyPath().toString().replaceAll("\\[.*", ""),
                    violation.getMessage());
        }
        if (request.imageSize() != null && request.imageSize() % 32 != 0) {
            errors.putIfAbsent("imageSize", "must be a multiple of 32");
        }
        if (request.classes() != null && new HashSet<>(request.classes()).size() != request.classes().size()) {
            errors.putIfAbsent("classes", "must not contain duplicates");
        }
        if (request.sourceType() != null && request.source() != null && !request.source().isBlank()) {
            String problem = request.sourceType() == DetectionSourceType.YOUTUBE_URL
                    ? youtubeProblem(request.source().strip()) : localPathProblem(request.source().strip());
            if (problem != null) {
                errors.putIfAbsent("source", problem);
            }
        }
        if (!errors.isEmpty()) {
            throw new InvalidDetectionJobException(errors);
        }
    }

    /** First-line check only; the worker canonicalises and revalidates before downloading. */
    private static String youtubeProblem(String source) {
        try {
            URI uri = new URI(source);
            String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
            String host = uri.getHost() == null ? "" : uri.getHost().toLowerCase(Locale.ROOT);
            if (!scheme.equals("https") && !scheme.equals("http")) {
                return "must be an http(s) YouTube URL";
            }
            if (uri.getRawUserInfo() != null || !YOUTUBE_HOSTS.contains(host)) {
                return "must be a supported YouTube video URL";
            }
            return null;
        } catch (URISyntaxException exception) {
            return "must be a valid URL";
        }
    }

    /** Relative to the worker's AI_LOCAL_INPUT_DIR; no absolute paths or parent segments. */
    private static String localPathProblem(String source) {
        if (!LOCAL_PATH.matcher(source).matches()) {
            return "must be a relative path using letters, digits, '.', '_', '-', and '/'";
        }
        for (String segment : source.split("/")) {
            if (segment.equals("..") || segment.equals(".")) {
                return "must not contain '.' or '..' segments";
            }
        }
        return null;
    }

    private JsonNode serialize(DetectionCommandMessage command) {
        return objectMapper.valueToTree(command);
    }
}
