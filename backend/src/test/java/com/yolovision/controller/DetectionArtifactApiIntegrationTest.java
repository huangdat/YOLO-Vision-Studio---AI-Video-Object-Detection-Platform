package com.yolovision.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.head;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.entity.ModelConfig;
import com.yolovision.exception.ArtifactTransferException;
import com.yolovision.repository.DetectionJobOutboxRepository;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.DetectionResultRepository;
import com.yolovision.repository.ModelConfigRepository;
import com.yolovision.storage.InMemoryObjectStorage;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.transaction.annotation.Transactional;

/** Artifact endpoints over MockMvc and H2, with an in-memory storage double. */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Transactional
@Import(DetectionArtifactApiIntegrationTest.Storage.class)
class DetectionArtifactApiIntegrationTest {

    @TestConfiguration
    static class Storage {
        @Bean
        @Primary
        InMemoryObjectStorage inMemoryObjectStorage() {
            return new InMemoryObjectStorage();
        }
    }

    private static final int VIDEO_SIZE = 200_000;
    private static final MediaType MP4 = MediaType.valueOf("video/mp4");

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private InMemoryObjectStorage storage;

    @Autowired
    private ModelConfigRepository models;

    @Autowired
    private DetectionJobRepository jobs;

    @Autowired
    private DetectionResultRepository results;

    @Autowired
    private DetectionJobOutboxRepository outbox;

    private final byte[] video = new byte[VIDEO_SIZE];
    private ModelConfig yolo11n;

    @BeforeEach
    void clean() {
        storage.reset();
        results.deleteAll();
        outbox.deleteAll();
        jobs.deleteAll();
        models.deleteAll();
        ModelConfig model = new ModelConfig("yolo11n", "YOLO11", "n", "DETECT", "yolo11n.pt");
        model.setEnabled(true);
        yolo11n = models.saveAndFlush(model);
        new Random(42).nextBytes(video);
    }

    // Video streaming -------------------------------------------------------------------------

    @Test
    void completedVideoStreamsInlineWithExactHeadersAndBytes() throws Exception {
        UUID id = completedJobWithArtifacts();

        MvcResult result = mockMvc.perform(get(url(id, "/video")))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MP4))
                .andExpect(header().string(HttpHeaders.ACCEPT_RANGES, "bytes"))
                .andExpect(header().longValue(HttpHeaders.CONTENT_LENGTH, VIDEO_SIZE))
                .andExpect(header().string(HttpHeaders.CONTENT_DISPOSITION,
                        "inline; filename=\"detection-" + id + ".mp4\""))
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(header().string("X-Content-Type-Options", "nosniff"))
                .andExpect(header().exists(HttpHeaders.ETAG))
                .andExpect(header().doesNotExist(HttpHeaders.CONTENT_RANGE))
                .andReturn();

        assertThat(result.getResponse().getContentAsByteArray()).isEqualTo(video);
        assertThat(storage.opens()).singleElement().satisfies(open -> {
            assertThat(open.offset()).isZero();
            assertThat(open.length()).isEqualTo(VIDEO_SIZE);
            assertThat(open.closed()).isTrue();
        });
    }

    @ParameterizedTest
    @ValueSource(strings = {"bytes=0-1023", "bytes=0-0", "bytes=100000-100999", "bytes=199999-199999",
        "bytes=150000-", "bytes=-2048", "bytes=190000-999999"})
    void singleRangesReturnPartialContentWithExactSlices(String rangeHeader) throws Exception {
        UUID id = completedJobWithArtifacts();
        long[] bounds = expectedBounds(rangeHeader);

        MvcResult result = mockMvc.perform(get(url(id, "/video")).header(HttpHeaders.RANGE, rangeHeader))
                .andExpect(status().isPartialContent())
                .andExpect(content().contentType(MP4))
                .andExpect(header().string(HttpHeaders.ACCEPT_RANGES, "bytes"))
                .andExpect(header().string(HttpHeaders.CONTENT_RANGE,
                        "bytes " + bounds[0] + "-" + bounds[1] + "/" + VIDEO_SIZE))
                .andExpect(header().longValue(HttpHeaders.CONTENT_LENGTH, bounds[1] - bounds[0] + 1))
                .andReturn();

        assertThat(result.getResponse().getContentAsByteArray())
                .isEqualTo(Arrays.copyOfRange(video, (int) bounds[0], (int) bounds[1] + 1));
        // Only the requested window is read from storage, and the stream is closed afterwards.
        assertThat(storage.opens()).singleElement().satisfies(open -> {
            assertThat(open.offset()).isEqualTo(bounds[0]);
            assertThat(open.length()).isEqualTo(bounds[1] - bounds[0] + 1);
            assertThat(open.closed()).isTrue();
        });
    }

    @ParameterizedTest
    @ValueSource(strings = {"bytes=200000-", "bytes=500000-600000", "bytes=-0"})
    void unsatisfiableRangesAnswer416WithTheObjectSize(String rangeHeader) throws Exception {
        UUID id = completedJobWithArtifacts();

        mockMvc.perform(get(url(id, "/video")).header(HttpHeaders.RANGE, rangeHeader))
                .andExpect(status().isRequestedRangeNotSatisfiable())
                .andExpect(header().string(HttpHeaders.CONTENT_RANGE, "bytes */" + VIDEO_SIZE))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("RANGE_NOT_SATISFIABLE"));
        assertThat(storage.opens()).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {"bytes=abc", "items=0-10", "bytes=10-5", "bytes=0-10,20-30"})
    void malformedAndMultiRangeHeadersFallBackToTheFullBody(String rangeHeader) throws Exception {
        UUID id = completedJobWithArtifacts();

        MvcResult result = mockMvc.perform(get(url(id, "/video")).header(HttpHeaders.RANGE, rangeHeader))
                .andExpect(status().isOk())
                .andExpect(header().doesNotExist(HttpHeaders.CONTENT_RANGE))
                .andExpect(header().longValue(HttpHeaders.CONTENT_LENGTH, VIDEO_SIZE))
                .andReturn();
        assertThat(result.getResponse().getContentAsByteArray()).isEqualTo(video);
        assertThat(result.getResponse().getContentType()).doesNotContain("multipart");
    }

    @Test
    void ifRangeWithAStaleValidatorReturnsTheFullBody() throws Exception {
        UUID id = completedJobWithArtifacts();
        String etag = mockMvc.perform(head(url(id, "/video"))).andReturn().getResponse().getHeader(HttpHeaders.ETAG);

        mockMvc.perform(get(url(id, "/video")).header(HttpHeaders.RANGE, "bytes=0-9").header(HttpHeaders.IF_RANGE, etag))
                .andExpect(status().isPartialContent());
        mockMvc.perform(get(url(id, "/video")).header(HttpHeaders.RANGE, "bytes=0-9")
                        .header(HttpHeaders.IF_RANGE, "\"stale\""))
                .andExpect(status().isOk())
                .andExpect(header().longValue(HttpHeaders.CONTENT_LENGTH, VIDEO_SIZE));
    }

    @Test
    void headReportsMetadataWithoutOpeningTheObject() throws Exception {
        UUID id = completedJobWithArtifacts();

        MvcResult result = mockMvc.perform(head(url(id, "/video")))
                .andExpect(status().isOk())
                .andExpect(header().longValue(HttpHeaders.CONTENT_LENGTH, VIDEO_SIZE))
                .andExpect(header().string(HttpHeaders.ACCEPT_RANGES, "bytes"))
                .andReturn();
        assertThat(result.getResponse().getContentAsByteArray()).isEmpty();
        assertThat(storage.opens()).isEmpty();
    }

    // Download ---------------------------------------------------------------------------------

    @Test
    void downloadSendsTheSameBytesAsAnAttachmentWithASafeName() throws Exception {
        UUID id = completedJobWithArtifacts();

        MvcResult result = mockMvc.perform(get(url(id, "/video/download")))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MP4))
                .andExpect(header().string(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"detection-" + id + ".mp4\""))
                .andExpect(header().longValue(HttpHeaders.CONTENT_LENGTH, VIDEO_SIZE))
                .andReturn();
        assertThat(result.getResponse().getContentAsByteArray()).isEqualTo(video);
    }

    @Test
    void downloadAlsoSupportsRangesForResumption() throws Exception {
        UUID id = completedJobWithArtifacts();

        MvcResult result = mockMvc.perform(get(url(id, "/video/download")).header(HttpHeaders.RANGE, "bytes=10-19"))
                .andExpect(status().isPartialContent())
                .andExpect(header().string(HttpHeaders.CONTENT_RANGE, "bytes 10-19/" + VIDEO_SIZE))
                .andReturn();
        assertThat(result.getResponse().getContentAsByteArray()).isEqualTo(Arrays.copyOfRange(video, 10, 20));
    }

    // Validation and failures (before streaming) -----------------------------------------------

    @ParameterizedTest
    @ValueSource(strings = {"/video", "/video/download", "/result.json", "/result.json/download"})
    void unknownJobsAre404(String path) throws Exception {
        mockMvc.perform(get(url(UUID.randomUUID(), path)))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("JOB_NOT_FOUND"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"/video", "/video/download", "/result.json", "/result.json/download"})
    void malformedJobIdsAre400(String path) throws Exception {
        mockMvc.perform(get("/api/v1/detections/not-a-uuid" + path))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_PARAMETER"));
    }

    @ParameterizedTest
    @EnumSource(value = DetectionJobStatus.class, names = "COMPLETED", mode = EnumSource.Mode.EXCLUDE)
    void unfinishedFailedAndCancelledJobsExposeNoArtifacts(DetectionJobStatus jobStatus) throws Exception {
        UUID id = job(jobStatus).getId();
        storage.put(key(id, "detected.mp4"), video, "video/mp4");

        for (String path : List.of("/video", "/video/download", "/result.json", "/result.json/download")) {
            mockMvc.perform(get(url(id, path)))
                    .andExpect(status().isConflict())
                    .andExpect(jsonPath("$.code").value("RESULT_NOT_READY"))
                    .andExpect(jsonPath("$.jobStatus").value(jobStatus.name()));
        }
        assertThat(storage.opens()).isEmpty();
    }

    @Test
    void completedJobWithoutAResultRowIsAControlledServerError() throws Exception {
        UUID id = job(DetectionJobStatus.COMPLETED).getId();

        mockMvc.perform(get(url(id, "/video")))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.code").value("RESULT_UNAVAILABLE"));
    }

    @Test
    void missingObjectsAre404WithoutRevealingStorageDetails() throws Exception {
        UUID id = completedJobWithArtifacts();
        storage.reset();

        String body = mockMvc.perform(get(url(id, "/video")))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("ARTIFACT_NOT_FOUND"))
                .andReturn().getResponse().getContentAsString();
        // "instance" is the request path; the object key, file name, and bucket never appear.
        assertThat(body).doesNotContain(key(id, "detected.mp4")).doesNotContain("detected.mp4")
                .doesNotContain("\"videos\"").doesNotContain("bucket");
        mockMvc.perform(get(url(id, "/result.json"))).andExpect(jsonPath("$.code").value("ARTIFACT_NOT_FOUND"));
    }

    @Test
    void emptyObjectsAreNotServed() throws Exception {
        UUID id = completedJobWithArtifacts();
        storage.put(key(id, "detected.mp4"), new byte[0], "video/mp4");

        mockMvc.perform(get(url(id, "/video")).header(HttpHeaders.RANGE, "bytes=0-1"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("ARTIFACT_NOT_FOUND"));
    }

    @Test
    void keysThatDoNotNameTheJobsOwnArtifactAreRefused() throws Exception {
        UUID id = job(DetectionJobStatus.COMPLETED).getId();
        UUID other = UUID.randomUUID();
        DetectionResult result = new DetectionResult(jobs.findById(id).orElseThrow(), key(other, "detected.mp4"),
                Map.of("bus", 1L));
        result.setResultJsonKey("detections/" + id + "/../" + other + "/result.json");
        results.saveAndFlush(result);
        storage.put(key(other, "detected.mp4"), video, "video/mp4");

        mockMvc.perform(get(url(id, "/video"))).andExpect(jsonPath("$.code").value("ARTIFACT_NOT_FOUND"));
        mockMvc.perform(get(url(id, "/result.json"))).andExpect(jsonPath("$.code").value("ARTIFACT_NOT_FOUND"));
        assertThat(storage.opens()).isEmpty();
    }

    @Test
    void legacyResultsWithoutAJsonKeyHaveNoJsonArtifact() throws Exception {
        UUID id = job(DetectionJobStatus.COMPLETED).getId();
        results.saveAndFlush(new DetectionResult(jobs.findById(id).orElseThrow(), key(id, "detected.mp4"),
                Map.of("bus", 1L)));
        storage.put(key(id, "detected.mp4"), video, "video/mp4");

        mockMvc.perform(get(url(id, "/result.json"))).andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("ARTIFACT_NOT_FOUND"));
        mockMvc.perform(get(url(id, "/video"))).andExpect(status().isOk());
    }

    @Test
    void storageOutagesAre503WithRetryAfter() throws Exception {
        UUID id = completedJobWithArtifacts();
        storage.setUnavailable(true);

        for (String path : List.of("/video", "/video/download", "/result.json")) {
            mockMvc.perform(get(url(id, path)))
                    .andExpect(status().isServiceUnavailable())
                    .andExpect(header().string(HttpHeaders.RETRY_AFTER, "10"))
                    .andExpect(jsonPath("$.code").value("STORAGE_UNAVAILABLE"));
        }
    }

    @Test
    void aStorageFailureAfterCommitAbortsInsteadOfReportingSuccess() throws Exception {
        UUID id = completedJobWithArtifacts();
        storage.failStreamsAfter(70_000);

        // The status is already committed; the failure propagates so the container aborts the connection.
        assertThatThrownBy(() -> mockMvc.perform(get(url(id, "/video"))))
                .hasRootCauseInstanceOf(java.io.IOException.class)
                .satisfies(error -> assertThat(rootChain(error)).anyMatch(ArtifactTransferException.class::isInstance));
        assertThat(storage.opens()).singleElement().satisfies(open -> assertThat(open.closed()).isTrue());
    }

    @Test
    void existingResultMetadataEndpointIsUnchanged() throws Exception {
        UUID id = completedJobWithArtifacts();

        mockMvc.perform(get(url(id, "/result")))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.outputVideoAvailable").value(true))
                .andExpect(jsonPath("$.resultMetadataAvailable").value(true))
                .andExpect(jsonPath("$.detectionSummary.bus").value(60));
        assertThat(storage.opens()).isEmpty();
    }

    // result.json --------------------------------------------------------------------------------

    @Test
    void resultJsonReturnsTheStoredBytesUnchanged() throws Exception {
        UUID id = completedJobWithArtifacts();
        byte[] stored = manifest(id).getBytes(StandardCharsets.UTF_8);

        MvcResult result = mockMvc.perform(get(url(id, "/result.json")))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(header().string(HttpHeaders.CONTENT_DISPOSITION,
                        "inline; filename=\"detection-" + id + "-result.json\""))
                .andExpect(header().string("X-Content-Type-Options", "nosniff"))
                .andExpect(jsonPath("$.statistics.detectionsByClass.bus").value(60))
                .andReturn();
        assertThat(result.getResponse().getContentAsByteArray()).isEqualTo(stored);
    }

    @Test
    void resultJsonDownloadIsAnAttachment() throws Exception {
        UUID id = completedJobWithArtifacts();

        MvcResult result = mockMvc.perform(get(url(id, "/result.json/download")))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(header().string(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"detection-" + id + "-result.json\""))
                .andReturn();
        assertThat(result.getResponse().getContentAsString(StandardCharsets.UTF_8)).isEqualTo(manifest(id));
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "{not json",
        "[1, 2, 3]",
        "{\"a\": 1} {\"b\": 2}",
        "{\"jobId\": \"00000000-0000-4000-8000-000000000000\"}",
        "{\"output\": {\"videoPath\": \"/data/outputs/x/detected.mp4\"}}",
        "{\"source\": \"C:\\\\videos\\\\clip.mp4\"}",
        "{\"minioSecretKey\": \"x\"}",
        "{\"auth\": {\"accessToken\": \"x\"}}"
    })
    void malformedForeignOrUnsafeResultJsonIsNotServed(String stored) throws Exception {
        UUID id = completedJobWithArtifacts();
        storage.put(key(id, "result.json"), stored.getBytes(StandardCharsets.UTF_8), "application/json");

        String body = mockMvc.perform(get(url(id, "/result.json")))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.code").value("ARTIFACT_INVALID"))
                .andReturn().getResponse().getContentAsString();
        assertThat(body).doesNotContain("/data/outputs").doesNotContain("videos\\\\");
    }

    @Test
    void resultJsonMustBeUtf8() throws Exception {
        UUID id = completedJobWithArtifacts();
        storage.put(key(id, "result.json"), new byte[] {'{', '"', 'a', '"', ':', '"', (byte) 0xff, '"', '}'},
                "application/json");

        mockMvc.perform(get(url(id, "/result.json"))).andExpect(jsonPath("$.code").value("ARTIFACT_INVALID"));
    }

    @Test
    void htmlInsideResultJsonIsReturnedAsInertJson() throws Exception {
        UUID id = completedJobWithArtifacts();
        String stored = "{\"jobId\":\"" + id + "\",\"note\":\"<script>alert(1)</script>\"}";
        storage.put(key(id, "result.json"), stored.getBytes(StandardCharsets.UTF_8), "application/json");

        mockMvc.perform(get(url(id, "/result.json")))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(header().string("X-Content-Type-Options", "nosniff"))
                .andExpect(content().string(stored));
    }

    // Helpers -------------------------------------------------------------------------------------

    private UUID completedJobWithArtifacts() {
        DetectionJob job = job(DetectionJobStatus.COMPLETED);
        UUID id = job.getId();
        DetectionResult result = new DetectionResult(job, key(id, "detected.mp4"), Map.of("bus", 60L));
        result.setResultJsonKey(key(id, "result.json"));
        result.setTotalFrames(60);
        result.setProcessingTimeMs(10_317L);
        results.saveAndFlush(result);
        storage.put(key(id, "detected.mp4"), video, "video/mp4");
        storage.put(key(id, "result.json"), manifest(id).getBytes(StandardCharsets.UTF_8), "application/json");
        return id;
    }

    private DetectionJob job(DetectionJobStatus jobStatus) {
        DetectionJob job = new DetectionJob(yolo11n, "https://www.youtube.com/watch?v=abcdefghijk",
                new BigDecimal("0.250"), 640, List.of(1, 2, 3, 5, 7));
        job.setStatus(jobStatus);
        job.setProgress(jobStatus == DetectionJobStatus.COMPLETED ? 100 : 0);
        return jobs.saveAndFlush(job);
    }

    private static String manifest(UUID id) {
        return """
                {
                  "modelKey": "yolo11n",
                  "statistics": {"totalFramesProcessed": 60, "detectionsByClass": {"bus": 60}},
                  "schemaVersion": 1,
                  "jobId": "%s",
                  "artifacts": {"outputVideoKey": "detections/%s/detected.mp4", "resultJsonKey": "detections/%s/result.json"},
                  "completedAt": "2026-11-08T11:13:38.785018Z"
                }""".formatted(id, id, id);
    }

    private static String key(UUID id, String name) {
        return "detections/" + id + "/" + name;
    }

    private static String url(UUID id, String path) {
        return "/api/v1/detections/" + id + path;
    }

    private static long[] expectedBounds(String header) {
        String spec = header.substring("bytes=".length());
        if (spec.startsWith("-")) {
            long suffix = Long.parseLong(spec.substring(1));
            return new long[] {VIDEO_SIZE - suffix, VIDEO_SIZE - 1};
        }
        String[] parts = spec.split("-", -1);
        long start = Long.parseLong(parts[0]);
        long end = parts[1].isEmpty() ? VIDEO_SIZE - 1 : Math.min(Long.parseLong(parts[1]), VIDEO_SIZE - 1);
        return new long[] {start, end};
    }

    private static java.util.stream.Stream<Throwable> rootChain(Throwable error) {
        return java.util.stream.Stream.iterate(error, java.util.Objects::nonNull, Throwable::getCause);
    }
}
