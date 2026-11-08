package com.yolovision.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.endsWith;
import static org.hamcrest.Matchers.hasKey;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.entity.DetectionSourceType;
import com.yolovision.entity.ModelConfig;
import com.yolovision.repository.DetectionJobOutboxRepository;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.DetectionResultRepository;
import com.yolovision.repository.ModelConfigRepository;
import com.yolovision.service.DetectionProgressStreamService;
import jakarta.persistence.EntityManager;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Transactional
class DetectionApiIntegrationTest {

    private static final String VIDEO = "https://www.youtube.com/watch?v=abcdefghijk";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ModelConfigRepository models;

    @Autowired
    private DetectionJobRepository jobs;

    @Autowired
    private DetectionResultRepository results;

    @Autowired
    private DetectionJobOutboxRepository outbox;

    @Autowired
    private DetectionProgressStreamService streams;

    @Autowired
    private EntityManager entityManager;

    @Autowired
    private JdbcTemplate jdbc;

    private ModelConfig yolo11n;
    private ModelConfig yolo26s;

    @BeforeEach
    void catalog() {
        results.deleteAll();
        outbox.deleteAll();
        jobs.deleteAll();
        models.deleteAll();
        yolo11n = model("yolo11n", "YOLO11", "n", "DETECT", true);
        yolo26s = model("yolo26s", "YOLO26", "s", "DETECT", false);
        model("yolo11n-seg", "YOLO11", "n", "SEGMENT", true);
        models.flush();
    }

    // POST /api/v1/detections --------------------------------------------------------------

    @Test
    void validSubmissionIsAcceptedPersistedAndQueuedThroughTheOutbox() throws Exception {
        MvcResult result = mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"videoUrl":"%s","modelKey":"yolo11n","confidence":0.4,"imageSize":640,"classes":[2,7]}
                                """.formatted(VIDEO)))
                .andExpect(status().isAccepted())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(header().string(HttpHeaders.LOCATION, org.hamcrest.Matchers.startsWith("/api/v1/detections/")))
                .andExpect(jsonPath("$.status").value("PENDING"))
                .andExpect(jsonPath("$.progress").value(0))
                .andExpect(jsonPath("$.modelKey").value("yolo11n"))
                .andExpect(jsonPath("$.message").value("Detection job accepted"))
                .andReturn();

        UUID jobId = UUID.fromString(com.jayway.jsonpath.JsonPath.read(result.getResponse().getContentAsString(), "$.jobId"));
        assertThat(result.getResponse().getHeader(HttpHeaders.LOCATION)).isEqualTo("/api/v1/detections/" + jobId);
        entityManager.flush();
        DetectionJob job = jobs.findById(jobId).orElseThrow();
        assertThat(job.getSourceType()).isEqualTo(DetectionSourceType.YOUTUBE_URL);
        assertThat(job.getVideoUrl()).isEqualTo(VIDEO);
        assertThat(job.getConfidence()).isEqualByComparingTo("0.400");
        assertThat(job.getSelectedClasses()).containsExactly(2, 7);
        assertThat(outbox.findByJobIdAndMessageType(jobId, "detection.execute.v1")).isPresent();
    }

    @ParameterizedTest
    @ValueSource(strings = {"https://youtu.be/abcdefghijk", "https://m.youtube.com/watch?v=abcdefghijk&t=30",
        "https://www.youtube.com/shorts/abcdefghijk", "http://youtube.com/embed/abcdefghijk"})
    void supportedUrlFormsAreStoredCanonically(String url) throws Exception {
        String body = mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"videoUrl\":\"" + url + "\",\"modelKey\":\"yolo11n\"}"))
                .andExpect(status().isAccepted()).andReturn().getResponse().getContentAsString();

        UUID jobId = UUID.fromString(com.jayway.jsonpath.JsonPath.read(body, "$.jobId"));
        assertThat(jobs.findById(jobId).orElseThrow().getVideoUrl()).isEqualTo(VIDEO);
    }

    @Test
    void omittedSettingsUseEngineDefaults() throws Exception {
        String body = mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"videoUrl\":\"" + VIDEO + "\",\"modelKey\":\"yolo11n\"}"))
                .andExpect(status().isAccepted()).andReturn().getResponse().getContentAsString();

        mockMvc.perform(get("/api/v1/detections/" + com.jayway.jsonpath.JsonPath.read(body, "$.jobId")))
                .andExpect(jsonPath("$.confidence").value(0.25))
                .andExpect(jsonPath("$.imageSize").value(960))
                .andExpect(jsonPath("$.classes").value(contains(1, 2, 3, 5, 7)));
    }

    @ParameterizedTest(name = "{0}")
    @CsvSource(delimiter = '|', value = {
        "missing video URL|{\"modelKey\":\"yolo11n\"}|videoUrl",
        "blank video URL|{\"videoUrl\":\" \",\"modelKey\":\"yolo11n\"}|videoUrl",
        "non-YouTube host|{\"videoUrl\":\"https://example.com/v.mp4\",\"modelKey\":\"yolo11n\"}|videoUrl",
        "YouTube playlist|{\"videoUrl\":\"https://www.youtube.com/playlist?list=PL123\",\"modelKey\":\"yolo11n\"}|videoUrl",
        "watch URL with playlist|{\"videoUrl\":\"https://www.youtube.com/watch?v=abcdefghijk&list=PL1\",\"modelKey\":\"yolo11n\"}|videoUrl",
        "channel URL|{\"videoUrl\":\"https://www.youtube.com/@channel\",\"modelKey\":\"yolo11n\"}|videoUrl",
        "malformed video id|{\"videoUrl\":\"https://youtu.be/short\",\"modelKey\":\"yolo11n\"}|videoUrl",
        "non-default port|{\"videoUrl\":\"https://www.youtube.com:8443/watch?v=abcdefghijk\",\"modelKey\":\"yolo11n\"}|videoUrl",
        "file URL|{\"videoUrl\":\"file:///etc/passwd\",\"modelKey\":\"yolo11n\"}|videoUrl",
        "local path|{\"videoUrl\":\"/data/inputs/clip.mp4\",\"modelKey\":\"yolo11n\"}|videoUrl",
        "missing model|{\"videoUrl\":\"https://youtu.be/abcdefghijk\"}|modelKey",
        "path-like model|{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"../x.pt\"}|modelKey",
        "confidence above one|{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"yolo11n\",\"confidence\":1.5}|confidence",
        "negative confidence|{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"yolo11n\",\"confidence\":-0.1}|confidence",
        "image size too small|{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"yolo11n\",\"imageSize\":0}|imageSize",
        "image size not a multiple of 32|{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"yolo11n\",\"imageSize\":650}|imageSize",
        "image size too large|{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"yolo11n\",\"imageSize\":8192}|imageSize",
        "empty classes|{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"yolo11n\",\"classes\":[]}|classes",
        "duplicate classes|{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"yolo11n\",\"classes\":[2,2]}|classes",
        "negative class|{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"yolo11n\",\"classes\":[-1]}|classes"
    })
    void invalidRequestsAreRejectedWithFieldErrorsAndCreateNothing(String description, String json, String field)
            throws Exception {
        mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON).content(json))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("INVALID_DETECTION_REQUEST"))
                .andExpect(jsonPath("$.detail").value("Detection request validation failed."))
                .andExpect(jsonPath("$.errors." + field).isNotEmpty())
                .andExpect(jsonPath("$.errors", not(hasKey("source"))))
                .andExpect(jsonPath("$.timestamp").isNotEmpty());
        assertThat(jobs.count()).isZero();
        assertThat(outbox.count()).isZero();
    }

    @Test
    void unknownModelIsNotFound() throws Exception {
        submit("yolov5s").andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("MODEL_NOT_FOUND"))
                .andExpect(jsonPath("$.errors.modelKey").value("is not registered"));
        assertThat(jobs.count()).isZero();
    }

    @Test
    void disabledModelIsAConflictAndIsNeverEnabledImplicitly() throws Exception {
        submit("yolo26s").andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("MODEL_DISABLED"));
        assertThat(models.findByModelKey("yolo26s").orElseThrow().isEnabled()).isFalse();
        assertThat(jobs.count()).isZero();
    }

    @Test
    void nonDetectionModelIsAConflict() throws Exception {
        submit("yolo11n-seg").andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("MODEL_NOT_SUPPORTED"));
    }

    @Test
    void unknownFieldsSuchAsLocalSourcesAreRejected() throws Exception {
        mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON).content("""
                        {"videoUrl":"%s","modelKey":"yolo11n","sourceType":"LOCAL_FILE","source":"clip.mp4"}
                        """.formatted(VIDEO)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("MALFORMED_REQUEST"))
                .andExpect(jsonPath("$.detail", not(org.hamcrest.Matchers.containsString("sourceType"))));
        assertThat(jobs.count()).isZero();
    }

    @ParameterizedTest
    @ValueSource(strings = {"{", "[]", "{\"videoUrl\":42,\"modelKey\":\"yolo11n\",\"confidence\":\"high\"}"})
    void malformedJsonIsABadRequest(String body) throws Exception {
        mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("MALFORMED_REQUEST"));
    }

    @Test
    void missingBodyIsAValidationError() throws Exception {
        mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_DETECTION_REQUEST"));
    }

    @Test
    void oversizeBodyIsRejectedBeforeParsing() throws Exception {
        String padding = "x".repeat(20_000);
        mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"videoUrl\":\"" + VIDEO + "\",\"modelKey\":\"yolo11n\",\"pad\":\"" + padding + "\"}"))
                .andExpect(status().isPayloadTooLarge())
                .andExpect(jsonPath("$.code").value("PAYLOAD_TOO_LARGE"));
        assertThat(jobs.count()).isZero();
    }

    @Test
    void nonJsonContentIsUnsupported() throws Exception {
        mockMvc.perform(post("/api/v1/detections").contentType(MediaType.TEXT_PLAIN).content(VIDEO))
                .andExpect(status().isUnsupportedMediaType())
                .andExpect(jsonPath("$.code").value("UNSUPPORTED_MEDIA_TYPE"));
    }

    // GET /api/v1/detections/{jobId} -----------------------------------------------------

    @Test
    void detailsReflectPersistedState() throws Exception {
        DetectionJob job = job(yolo11n, DetectionJobStatus.DETECTING, 65);
        jdbc.update("UPDATE detection_jobs SET started_at = ? WHERE id = ?", Timestamp.from(Instant.now()), job.getId());
        entityManager.clear();

        mockMvc.perform(get("/api/v1/detections/" + job.getId()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.jobId").value(job.getId().toString()))
                .andExpect(jsonPath("$.modelKey").value("yolo11n"))
                .andExpect(jsonPath("$.modelVersion").value("YOLO11"))
                .andExpect(jsonPath("$.status").value("DETECTING"))
                .andExpect(jsonPath("$.progress").value(65))
                .andExpect(jsonPath("$.confidence").value(0.25))
                .andExpect(jsonPath("$.imageSize").value(640))
                .andExpect(jsonPath("$.classes").value(contains(2, 5)))
                .andExpect(jsonPath("$.videoUrl").value(VIDEO))
                .andExpect(jsonPath("$.startedAt").isNotEmpty())
                .andExpect(jsonPath("$.completedAt").doesNotExist())
                .andExpect(jsonPath("$.errorCode").doesNotExist());
    }

    @Test
    void failedJobsExposeTheStoredSanitizedErrorOnly() throws Exception {
        DetectionJob job = job(yolo11n, DetectionJobStatus.FAILED, 30);
        jdbc.update("UPDATE detection_jobs SET error_code = 'VIDEO_DOWNLOAD_FAILED', error_message = "
                + "'The YouTube video could not be downloaded.' WHERE id = ?", job.getId());
        entityManager.clear();

        mockMvc.perform(get("/api/v1/detections/" + job.getId()))
                .andExpect(jsonPath("$.status").value("FAILED"))
                .andExpect(jsonPath("$.errorCode").value("VIDEO_DOWNLOAD_FAILED"))
                .andExpect(jsonPath("$.errorMessage").value("The YouTube video could not be downloaded."));
    }

    @Test
    void localDevelopmentSourcesAreNotExposed() throws Exception {
        DetectionJob job = job(yolo11n, DetectionJobStatus.PENDING, 0);
        jdbc.update("UPDATE detection_jobs SET source_type = 'LOCAL_FILE', video_url = 'clips/private.mp4' WHERE id = ?",
                job.getId());
        entityManager.clear();

        mockMvc.perform(get("/api/v1/detections/" + job.getId()))
                .andExpect(jsonPath("$.sourceType").value("LOCAL_FILE"))
                .andExpect(jsonPath("$.videoUrl").doesNotExist());
    }

    @Test
    void unknownJobIsNotFound() throws Exception {
        mockMvc.perform(get("/api/v1/detections/" + UUID.randomUUID()))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("JOB_NOT_FOUND"));
    }

    @Test
    void malformedJobIdIsABadRequestWithoutEchoingInput() throws Exception {
        mockMvc.perform(get("/api/v1/detections/not-a-uuid<script>"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_PARAMETER"))
                .andExpect(jsonPath("$.detail").value("Parameter 'jobId' must be a valid UUID."));
    }

    // GET /api/v1/detections -------------------------------------------------------------

    @Test
    void emptyHistoryIsAnEmptyPage() throws Exception {
        mockMvc.perform(get("/api/v1/detections"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.content").isEmpty())
                .andExpect(jsonPath("$.page").value(0))
                .andExpect(jsonPath("$.size").value(10))
                .andExpect(jsonPath("$.totalElements").value(0))
                .andExpect(jsonPath("$.totalPages").value(0));
    }

    @Test
    void historyIsPagedNewestFirstWithAStableTieBreaker() throws Exception {
        Instant base = Instant.parse("2026-11-08T09:00:00Z");
        for (int index = 0; index < 12; index++) {
            DetectionJob job = job(yolo11n, DetectionJobStatus.QUEUED, 0);
            jdbc.update("UPDATE detection_jobs SET created_at = ? WHERE id = ?",
                    Timestamp.from(base.plusSeconds(index)), job.getId());
        }
        entityManager.clear();

        mockMvc.perform(get("/api/v1/detections").param("page", "2").param("size", "5"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.content.length()").value(2))
                .andExpect(jsonPath("$.page").value(2))
                .andExpect(jsonPath("$.size").value(5))
                .andExpect(jsonPath("$.totalElements").value(12))
                .andExpect(jsonPath("$.totalPages").value(3))
                .andExpect(jsonPath("$.content[0].createdAt").value("2026-11-08T09:00:01Z"))
                .andExpect(jsonPath("$.content[1].createdAt").value("2026-11-08T09:00:00Z"));
        mockMvc.perform(get("/api/v1/detections").param("size", "1"))
                .andExpect(jsonPath("$.content[0].createdAt").value("2026-11-08T09:00:11Z"));

        // Equal timestamps are ordered by id descending.
        jdbc.update("UPDATE detection_jobs SET created_at = ?", Timestamp.from(base));
        entityManager.clear();
        List<String> ids = jobs.findAll().stream().map(job -> job.getId().toString()).sorted().toList();
        mockMvc.perform(get("/api/v1/detections").param("size", "2"))
                .andExpect(jsonPath("$.content[*].jobId").value(contains(ids.get(11), ids.get(10))));
    }

    @Test
    void historyFiltersByStatusAndModel() throws Exception {
        ModelConfig other = model("yolov8n", "YOLOv8", "n", "DETECT", true);
        job(yolo11n, DetectionJobStatus.COMPLETED, 100);
        job(yolo11n, DetectionJobStatus.FAILED, 10);
        job(other, DetectionJobStatus.COMPLETED, 100);

        mockMvc.perform(get("/api/v1/detections").param("status", "COMPLETED"))
                .andExpect(jsonPath("$.totalElements").value(2));
        mockMvc.perform(get("/api/v1/detections").param("modelKey", "yolov8n"))
                .andExpect(jsonPath("$.totalElements").value(1))
                .andExpect(jsonPath("$.content[0].modelKey").value("yolov8n"));
        mockMvc.perform(get("/api/v1/detections").param("status", "FAILED").param("modelKey", "yolo11n"))
                .andExpect(jsonPath("$.totalElements").value(1))
                .andExpect(jsonPath("$.content[0].status").value("FAILED"));
        mockMvc.perform(get("/api/v1/detections").param("modelKey", "yolo12x"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.content").isEmpty());
    }

    @ParameterizedTest
    @CsvSource({"page,-1", "size,0", "size,101", "status,RUNNING", "modelKey,../x", "page,abc"})
    void invalidHistoryParametersAreRejected(String name, String value) throws Exception {
        mockMvc.perform(get("/api/v1/detections").param(name, value))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.errors." + name).isNotEmpty());
    }

    // GET /api/v1/detections/{jobId}/result ------------------------------------------------

    @Test
    void completedResultReturnsPersistedStatisticsWithoutStorageLocations() throws Exception {
        DetectionJob job = job(yolo11n, DetectionJobStatus.COMPLETED, 100);
        DetectionResult result = new DetectionResult(job, "detections/" + job.getId() + "/detected.mp4",
                Map.of("bus", 60L, "car", 12L));
        result.setResultJsonKey("detections/" + job.getId() + "/result.json");
        result.setTotalFrames(60);
        result.setProcessingTimeMs(10833L);
        results.saveAndFlush(result);

        String body = mockMvc.perform(get("/api/v1/detections/" + job.getId() + "/result"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("COMPLETED"))
                .andExpect(jsonPath("$.modelKey").value("yolo11n"))
                .andExpect(jsonPath("$.totalFrames").value(60))
                .andExpect(jsonPath("$.processingTimeMs").value(10833))
                .andExpect(jsonPath("$.detectionSummary.bus").value(60))
                .andExpect(jsonPath("$.detectionSummary.car").value(12))
                .andExpect(jsonPath("$.totalDetections").value(72))
                .andExpect(jsonPath("$.countSemantics").value("BOUNDING_BOX_DETECTIONS_ACROSS_FRAMES"))
                .andExpect(jsonPath("$.outputVideoAvailable").value(true))
                .andExpect(jsonPath("$.resultMetadataAvailable").value(true))
                .andReturn().getResponse().getContentAsString();
        assertThat(body).doesNotContain("detections/", "minio", "http");
    }

    @ParameterizedTest
    @ValueSource(strings = {"PENDING", "QUEUED", "DETECTING", "UPLOADING", "FAILED", "CANCELLED"})
    void resultsOfUnfinishedOrUnsuccessfulJobsAreNotReady(String status) throws Exception {
        DetectionJob job = job(yolo11n, DetectionJobStatus.valueOf(status), 50);

        mockMvc.perform(get("/api/v1/detections/" + job.getId() + "/result"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("RESULT_NOT_READY"))
                .andExpect(jsonPath("$.jobStatus").value(status));
    }

    @Test
    void resultOfUnknownJobIsNotFound() throws Exception {
        mockMvc.perform(get("/api/v1/detections/" + UUID.randomUUID() + "/result"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("JOB_NOT_FOUND"));
    }

    @Test
    void completedJobWithoutAResultRowIsAControlledServerError() throws Exception {
        DetectionJob job = job(yolo11n, DetectionJobStatus.COMPLETED, 100);

        mockMvc.perform(get("/api/v1/detections/" + job.getId() + "/result"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.code").value("RESULT_UNAVAILABLE"))
                .andExpect(jsonPath("$.totalFrames").doesNotExist());
    }

    // GET /api/v1/detections/{jobId}/events ------------------------------------------------

    @Test
    void streamSendsSnapshotThenChangesThenCompletesAtTerminalState() throws Exception {
        DetectionJob job = job(yolo11n, DetectionJobStatus.QUEUED, 0);

        MvcResult stream = mockMvc.perform(get("/api/v1/detections/" + job.getId() + "/events")
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted())
                .andExpect(header().string("X-Accel-Buffering", "no"))
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andReturn();
        assertThat(stream.getResponse().getContentAsString())
                .contains("event:detection.progress", "\"status\":\"QUEUED\"", "retry:3000");

        streams.poll();
        assertThat(count(stream, "event:")).isEqualTo(1);

        jdbc.update("UPDATE detection_jobs SET status = 'DETECTING', progress = 40 WHERE id = ?", job.getId());
        streams.poll();
        jdbc.update("UPDATE detection_jobs SET status = 'COMPLETED', progress = 100 WHERE id = ?", job.getId());
        streams.poll();

        mockMvc.perform(asyncDispatch(stream)).andExpect(status().isOk());
        String body = stream.getResponse().getContentAsString();
        assertThat(count(stream, "event:")).isEqualTo(3);
        assertThat(body).contains("\"status\":\"DETECTING\",\"progress\":40", "event:detection.completed",
                "\"status\":\"COMPLETED\",\"progress\":100");
        assertThat(stream.getResponse().getContentType()).startsWith(MediaType.TEXT_EVENT_STREAM_VALUE);
    }

    @Test
    void streamForAFinishedJobSendsTheTerminalEventAndCloses() throws Exception {
        DetectionJob job = job(yolo11n, DetectionJobStatus.FAILED, 20);
        jdbc.update("UPDATE detection_jobs SET error_code = 'INVALID_SOURCE', error_message = 'Bad video' WHERE id = ?",
                job.getId());
        int before = streams.openStreams();

        MvcResult stream = mockMvc.perform(get("/api/v1/detections/" + job.getId() + "/events")
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted()).andReturn();
        mockMvc.perform(asyncDispatch(stream)).andExpect(status().isOk());

        assertThat(stream.getResponse().getContentAsString())
                .contains("event:detection.failed", "\"errorCode\":\"INVALID_SOURCE\"", "\"message\":\"Bad video\"");
        assertThat(streams.openStreams()).isEqualTo(before);
    }

    @Test
    void streamForUnknownJobIsAJsonNotFoundEvenForEventSourceClients() throws Exception {
        mockMvc.perform(get("/api/v1/detections/" + UUID.randomUUID() + "/events").accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("JOB_NOT_FOUND"));
    }

    @Test
    void streamWithMalformedIdIsABadRequest() throws Exception {
        mockMvc.perform(get("/api/v1/detections/123/events").accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(status().isBadRequest());
    }

    @Test
    void existingSystemAndModelApisStillWork() throws Exception {
        mockMvc.perform(get("/api/v1/system/info")).andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));
        mockMvc.perform(get("/api/v1/models/yolo11n")).andExpect(status().isOk());
        mockMvc.perform(get("/api/v1/models/none")).andExpect(status().isNotFound())
                .andExpect(jsonPath("$.title").value("Model not found"))
                .andExpect(jsonPath("$.code").value("MODEL_NOT_FOUND"));
    }

    @Test
    void openApiDocumentDescribesTheDetectionEndpoints() throws Exception {
        mockMvc.perform(get("/api/v1/openapi"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.paths['/api/v1/detections'].post").exists())
                .andExpect(jsonPath("$.paths['/api/v1/detections/{jobId}/events'].get").exists())
                .andExpect(jsonPath("$.paths['/api/v1/detections/{jobId}/result'].get").exists());
    }

    @Test
    void frontendOriginMayPostDetections() throws Exception {
        mockMvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders
                        .options("/api/v1/detections")
                        .header(HttpHeaders.ORIGIN, "http://localhost:5173")
                        .header(HttpHeaders.ACCESS_CONTROL_REQUEST_METHOD, "POST")
                        .header(HttpHeaders.ACCESS_CONTROL_REQUEST_HEADERS, "Content-Type"))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.ACCESS_CONTROL_ALLOW_METHODS,
                        org.hamcrest.Matchers.containsString("POST")));
    }

    private org.springframework.test.web.servlet.ResultActions submit(String modelKey) throws Exception {
        return mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON)
                .content("{\"videoUrl\":\"" + VIDEO + "\",\"modelKey\":\"" + modelKey + "\"}"));
    }

    private static int count(MvcResult result, String token) throws Exception {
        String body = result.getResponse().getContentAsString();
        return (body.length() - body.replace(token, "").length()) / token.length();
    }

    private ModelConfig model(String key, String version, String size, String task, boolean enabled) {
        ModelConfig model = new ModelConfig(key, version, size, task, key + ".pt");
        model.setEnabled(enabled);
        return models.save(model);
    }

    private DetectionJob job(ModelConfig model, DetectionJobStatus status, int progress) {
        DetectionJob job = new DetectionJob(model, VIDEO, new BigDecimal("0.250"), 640, List.of(2, 5));
        job.setStatus(status);
        job.setProgress(progress);
        return jobs.saveAndFlush(job);
    }
}
