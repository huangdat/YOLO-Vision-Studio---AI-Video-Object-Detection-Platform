package com.yolovision.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.yolovision.dto.DetectionJobSubmissionRequest;
import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobOutboxMessage;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionSourceType;
import com.yolovision.entity.ModelConfig;
import com.yolovision.exception.InvalidDetectionJobException;
import com.yolovision.repository.DetectionJobOutboxRepository;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.ModelConfigRepository;
import jakarta.persistence.EntityManager;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.stream.Stream;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@ActiveProfiles("test")
@Transactional
class DetectionJobSubmissionServiceTest {

    @Autowired
    private DetectionJobSubmissionService service;

    @Autowired
    private ModelConfigRepository models;

    @Autowired
    private DetectionJobRepository jobs;

    @Autowired
    private DetectionJobOutboxRepository outbox;

    @Autowired
    private EntityManager entityManager;

    @BeforeEach
    void registerModels() {
        outbox.deleteAll();
        jobs.deleteAll();
        models.deleteAll();
        ModelConfig enabled = new ModelConfig("yolo11n", "YOLO11", "n", "DETECT", "yolo11n.pt");
        enabled.setEnabled(true);
        models.save(enabled);
        models.save(new ModelConfig("yolo26s", "YOLO26", "s", "DETECT", "yolo26s.pt"));
        ModelConfig segment = new ModelConfig("yolo11n-seg", "YOLO11", "n", "SEGMENT", "yolo11n-seg.pt");
        segment.setEnabled(true);
        models.save(segment);
        models.flush();
    }

    @Test
    void validSubmissionCreatesAPendingJobAndOneOutboxCommandAtomically() {
        UUID jobId = service.submit(request("yolo11n", DetectionSourceType.YOUTUBE_URL,
                "https://www.youtube.com/watch?v=abcdefghijk", new BigDecimal("0.4"), 640, List.of(2, 7)));
        entityManager.flush();
        entityManager.clear();

        DetectionJob job = jobs.findById(jobId).orElseThrow();
        assertThat(job.getStatus()).isEqualTo(DetectionJobStatus.PENDING);
        assertThat(job.getProgress()).isZero();
        assertThat(job.getSourceType()).isEqualTo(DetectionSourceType.YOUTUBE_URL);
        assertThat(job.getVideoUrl()).isEqualTo("https://www.youtube.com/watch?v=abcdefghijk");
        assertThat(job.getConfidence()).isEqualByComparingTo("0.400");
        assertThat(job.getImageSize()).isEqualTo(640);
        assertThat(job.getSelectedClasses()).containsExactly(2, 7);

        DetectionJobOutboxMessage message = outbox.findByJobIdAndMessageType(jobId, "detection.execute.v1")
                .orElseThrow();
        assertThat(message.getStatus()).isEqualTo(DetectionJobOutboxMessage.Status.PENDING);
        assertThat(message.getAttempts()).isZero();
        JsonNode payload = message.getPayload();
        assertThat(payload.get("schemaVersion").asInt()).isEqualTo(1);
        assertThat(payload.get("messageId").asText()).isEqualTo(message.getId().toString());
        assertThat(payload.get("jobId").asText()).isEqualTo(jobId.toString());
        assertThat(payload.get("modelKey").asText()).isEqualTo("yolo11n");
        assertThat(payload.get("sourceType").asText()).isEqualTo("YOUTUBE_URL");
        assertThat(payload.get("source").asText()).isEqualTo("https://www.youtube.com/watch?v=abcdefghijk");
        assertThat(payload.get("confidence").decimalValue()).isEqualByComparingTo("0.4");
        assertThat(payload.get("imageSize").asInt()).isEqualTo(640);
        assertThat(payload.get("classes")).extracting(JsonNode::asInt).containsExactly(2, 7);
        assertThat(payload.get("createdAt").isTextual()).isTrue();
    }

    @Test
    void contractFieldNamesAreExactlyTheVersionOneCommand() {
        UUID jobId = service.submit(request("yolo11n", DetectionSourceType.LOCAL_FILE, "clips/street.mp4",
                null, null, null));
        List<String> fields = new ArrayList<>();
        outbox.findByJobIdAndMessageType(jobId, "detection.execute.v1").orElseThrow()
                .getPayload().fieldNames().forEachRemaining(fields::add);

        assertThat(fields).containsExactlyInAnyOrder("schemaVersion", "messageId", "jobId", "modelKey",
                "sourceType", "source", "confidence", "imageSize", "classes", "createdAt");
    }

    @Test
    void omittedSettingsUseTheEngineDefaults() {
        UUID jobId = service.submit(request("yolo11n", DetectionSourceType.LOCAL_FILE, "clips/street.mp4",
                null, null, null));
        entityManager.flush();
        entityManager.clear();

        DetectionJob job = jobs.findById(jobId).orElseThrow();
        assertThat(job.getConfidence()).isEqualByComparingTo("0.250");
        assertThat(job.getImageSize()).isEqualTo(960);
        assertThat(job.getSelectedClasses()).containsExactly(1, 2, 3, 5, 7);
        assertThat(job.getSourceType()).isEqualTo(DetectionSourceType.LOCAL_FILE);
    }

    @Test
    void unregisteredModelIsRejected() {
        assertRejected(request("yolov5s", DetectionSourceType.LOCAL_FILE, "a.mp4", null, null, null),
                "modelKey", "is not registered");
    }

    @Test
    void disabledModelIsRejectedEvenThoughItIsCataloged() {
        assertRejected(request("yolo26s", DetectionSourceType.LOCAL_FILE, "a.mp4", null, null, null),
                "modelKey", "is not enabled for detection");
    }

    @Test
    void nonDetectionModelIsRejected() {
        assertRejected(request("yolo11n-seg", DetectionSourceType.LOCAL_FILE, "a.mp4", null, null, null),
                "modelKey", "is not an object detection model");
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("invalidRequests")
    void invalidConfigurationIsRejectedWithoutCreatingAnything(String description,
            DetectionJobSubmissionRequest request, String field) {
        assertThatThrownBy(() -> service.submit(request))
                .isInstanceOfSatisfying(InvalidDetectionJobException.class,
                        exception -> assertThat(exception.getErrors()).containsKey(field));
        assertThat(jobs.count()).isZero();
        assertThat(outbox.count()).isZero();
    }

    static Stream<Arguments> invalidRequests() {
        DetectionSourceType local = DetectionSourceType.LOCAL_FILE;
        DetectionSourceType youtube = DetectionSourceType.YOUTUBE_URL;
        return Stream.of(
                Arguments.of("confidence above one", request("yolo11n", local, "a.mp4", new BigDecimal("1.5"), null, null), "confidence"),
                Arguments.of("negative confidence", request("yolo11n", local, "a.mp4", new BigDecimal("-0.1"), null, null), "confidence"),
                Arguments.of("confidence with four decimals", request("yolo11n", local, "a.mp4", new BigDecimal("0.2555"), null, null), "confidence"),
                Arguments.of("image size too small", request("yolo11n", local, "a.mp4", null, 16, null), "imageSize"),
                Arguments.of("image size too large", request("yolo11n", local, "a.mp4", null, 8192, null), "imageSize"),
                Arguments.of("image size not a stride multiple", request("yolo11n", local, "a.mp4", null, 650, null), "imageSize"),
                Arguments.of("empty classes", request("yolo11n", local, "a.mp4", null, null, List.of()), "classes"),
                Arguments.of("duplicate classes", request("yolo11n", local, "a.mp4", null, null, List.of(2, 2)), "classes"),
                Arguments.of("negative class", request("yolo11n", local, "a.mp4", null, null, List.of(-1)), "classes"),
                Arguments.of("missing model", request(null, local, "a.mp4", null, null, null), "modelKey"),
                Arguments.of("path-like model", request("../yolo11n.pt", local, "a.mp4", null, null, null), "modelKey"),
                Arguments.of("missing source type", request("yolo11n", null, "a.mp4", null, null, null), "sourceType"),
                Arguments.of("blank source", request("yolo11n", local, " ", null, null, null), "source"),
                Arguments.of("non-YouTube URL", request("yolo11n", youtube, "https://example.com/v.mp4", null, null, null), "source"),
                Arguments.of("YouTube URL with credentials", request("yolo11n", youtube, "https://user:pw@www.youtube.com/watch?v=abcdefghijk", null, null, null), "source"),
                Arguments.of("non-http scheme", request("yolo11n", youtube, "file:///etc/passwd", null, null, null), "source"),
                Arguments.of("absolute local path", request("yolo11n", local, "/etc/passwd", null, null, null), "source"),
                Arguments.of("windows local path", request("yolo11n", local, "C:\\videos\\a.mp4", null, null, null), "source"),
                Arguments.of("parent traversal", request("yolo11n", local, "clips/../../secret.mp4", null, null, null), "source"));
    }

    private void assertRejected(DetectionJobSubmissionRequest request, String field, String reason) {
        assertThatThrownBy(() -> service.submit(request))
                .isInstanceOfSatisfying(InvalidDetectionJobException.class,
                        exception -> assertThat(exception.getErrors()).containsEntry(field, reason));
        assertThat(jobs.count()).isZero();
        assertThat(outbox.count()).isZero();
    }

    private static DetectionJobSubmissionRequest request(String model, DetectionSourceType type, String source,
            BigDecimal confidence, Integer imageSize, List<Integer> classes) {
        return new DetectionJobSubmissionRequest(model, type, source, confidence, imageSize, classes);
    }
}
