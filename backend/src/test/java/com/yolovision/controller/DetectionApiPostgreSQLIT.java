package com.yolovision.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.jayway.jsonpath.JsonPath;
import com.yolovision.dto.messaging.DetectionEventMessage;
import com.yolovision.dto.messaging.DetectionEventStatus;
import com.yolovision.service.DetectionJobLifecycleService;
import com.yolovision.service.DetectionProgressStreamService;
import jakarta.persistence.EntityManagerFactory;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.hibernate.SessionFactory;
import org.hibernate.stat.Statistics;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

/** The detection REST API on real PostgreSQL 17 with the production Flyway migrations. */
@SpringBootTest(properties = {
    "app.detection-stream.poll-interval=1h",
    "spring.jpa.properties.hibernate.generate_statistics=true"
})
@AutoConfigureMockMvc
@ActiveProfiles("postgres-test")
@Testcontainers
class DetectionApiPostgreSQLIT {

    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:17-bookworm");

    @DynamicPropertySource
    static void isolatedPostgresqlDatasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
    }

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JdbcTemplate jdbc;

    @Autowired
    private DetectionJobLifecycleService lifecycle;

    @Autowired
    private DetectionProgressStreamService streams;

    @Autowired
    private EntityManagerFactory entityManagerFactory;

    @BeforeEach
    void freshJobsWithOneEnabledModel() {
        jdbc.update("DELETE FROM detection_jobs");
        jdbc.update("UPDATE model_configs SET enabled = (model_key IN ('yolo11n', 'yolov8n'))");
    }

    @Test
    void submissionPersistsTheJobAndItsOutboxCommandInPostgresql() throws Exception {
        UUID jobId = submit("yolo11n", "https://youtu.be/abcdefghijk");

        Map<String, Object> row = jdbc.queryForMap("""
                SELECT j.status, j.progress, j.source_type, j.video_url, j.selected_classes::text AS classes,
                       o.status AS outbox, o.payload ->> 'modelKey' AS model, o.payload ->> 'source' AS source
                FROM detection_jobs j JOIN detection_job_outbox o ON o.job_id = j.id WHERE j.id = ?
                """, jobId);
        assertThat(row).containsEntry("status", "PENDING").containsEntry("progress", 0)
                .containsEntry("source_type", "YOUTUBE_URL")
                .containsEntry("video_url", "https://www.youtube.com/watch?v=abcdefghijk")
                .containsEntry("classes", "[1, 2, 3, 5, 7]")
                .containsEntry("outbox", "PENDING").containsEntry("model", "yolo11n")
                .containsEntry("source", "https://www.youtube.com/watch?v=abcdefghijk");
    }

    @Test
    void disabledSeededModelsAreRejectedOnPostgresql() throws Exception {
        mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"videoUrl\":\"https://youtu.be/abcdefghijk\",\"modelKey\":\"yolo26s\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("MODEL_DISABLED"));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM detection_jobs", Long.class)).isZero();
    }

    @Test
    void historyPagesFiltersAndSortsOnPostgresqlWithoutNPlusOneQueries() throws Exception {
        for (int index = 0; index < 7; index++) {
            UUID id = submit(index % 2 == 0 ? "yolo11n" : "yolov8n", "https://youtu.be/abcdefghijk");
            jdbc.update("UPDATE detection_jobs SET created_at = TIMESTAMPTZ '2026-11-08 09:00:00+00' + (? * INTERVAL '1 second') "
                    + "WHERE id = ?", index, id);
        }
        jdbc.update("UPDATE detection_jobs SET status = 'COMPLETED', progress = 100 "
                + "WHERE created_at = TIMESTAMPTZ '2026-11-08 09:00:06+00'");
        Statistics statistics = entityManagerFactory.unwrap(SessionFactory.class).getStatistics();
        statistics.clear();

        mockMvc.perform(get("/api/v1/detections").param("size", "3").param("page", "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalElements").value(7))
                .andExpect(jsonPath("$.totalPages").value(3))
                .andExpect(jsonPath("$.content.length()").value(3))
                .andExpect(jsonPath("$.content[0].createdAt").value("2026-11-08T09:00:03Z"));
        // One page query (models fetched in the same statement) plus one count query.
        assertThat(statistics.getPrepareStatementCount()).isLessThanOrEqualTo(2);

        mockMvc.perform(get("/api/v1/detections").param("modelKey", "yolov8n"))
                .andExpect(jsonPath("$.totalElements").value(3));
        mockMvc.perform(get("/api/v1/detections").param("status", "COMPLETED").param("modelKey", "yolo11n"))
                .andExpect(jsonPath("$.totalElements").value(1))
                .andExpect(jsonPath("$.content[0].progress").value(100));
    }

    @Test
    void completedLifecycleIsVisibleThroughDetailsResultAndStream() throws Exception {
        UUID jobId = submit("yolo11n", "https://www.youtube.com/watch?v=abcdefghijk");
        lifecycle.markQueued(jobId);
        lifecycle.apply(event(jobId, DetectionEventStatus.DETECTING, 40, null, null));

        MvcResult stream = mockMvc.perform(get("/api/v1/detections/" + jobId + "/events")
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted()).andReturn();
        assertThat(stream.getResponse().getContentAsString()).contains("\"status\":\"DETECTING\",\"progress\":40");

        lifecycle.apply(event(jobId, DetectionEventStatus.COMPLETED, 100, "yolo11n", new DetectionEventMessage.Result(
                "detections/" + jobId + "/detected.mp4", "detections/" + jobId + "/result.json", 60, 10833L,
                Map.of("bus", 60L))));
        streams.poll();
        mockMvc.perform(asyncDispatch(stream)).andExpect(status().isOk());
        assertThat(stream.getResponse().getContentAsString()).contains("event:detection.completed");

        mockMvc.perform(get("/api/v1/detections/" + jobId))
                .andExpect(jsonPath("$.status").value("COMPLETED"))
                .andExpect(jsonPath("$.progress").value(100))
                .andExpect(jsonPath("$.startedAt").isNotEmpty())
                .andExpect(jsonPath("$.completedAt").isNotEmpty());
        mockMvc.perform(get("/api/v1/detections/" + jobId + "/result"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalFrames").value(60))
                .andExpect(jsonPath("$.processingTimeMs").value(10833))
                .andExpect(jsonPath("$.detectionSummary.bus").value(60))
                .andExpect(jsonPath("$.totalDetections").value(60))
                .andExpect(jsonPath("$.outputVideoAvailable").value(true));
        assertThat(jdbc.queryForObject("SELECT jsonb_typeof(detection_summary) FROM detection_results WHERE job_id = ?",
                String.class, jobId)).isEqualTo("object");
    }

    @Test
    void failedJobIsReportedWithItsCodeAndHasNoResult() throws Exception {
        UUID jobId = submit("yolo11n", "https://youtu.be/abcdefghijk");
        lifecycle.apply(event(jobId, DetectionEventStatus.FAILED, 12, null, null));

        mockMvc.perform(get("/api/v1/detections/" + jobId))
                .andExpect(jsonPath("$.status").value("FAILED"))
                .andExpect(jsonPath("$.errorCode").value("VIDEO_DOWNLOAD_FAILED"));
        mockMvc.perform(get("/api/v1/detections/" + jobId + "/result"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("RESULT_NOT_READY"))
                .andExpect(jsonPath("$.jobStatus").value("FAILED"));
    }

    private UUID submit(String model, String url) throws Exception {
        String body = mockMvc.perform(post("/api/v1/detections").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"videoUrl\":\"" + url + "\",\"modelKey\":\"" + model + "\",\"imageSize\":320}"))
                .andExpect(status().isAccepted())
                .andExpect(header().exists(HttpHeaders.LOCATION))
                .andReturn().getResponse().getContentAsString();
        return UUID.fromString(JsonPath.read(body, "$.jobId"));
    }

    private static DetectionEventMessage event(UUID jobId, DetectionEventStatus status, int progress, String model,
            DetectionEventMessage.Result result) {
        DetectionEventMessage.Error error = status == DetectionEventStatus.FAILED
                ? new DetectionEventMessage.Error("VIDEO_DOWNLOAD_FAILED", "The video could not be downloaded.", true)
                : null;
        return new DetectionEventMessage(1, UUID.randomUUID(), jobId, status, progress, null, null, null,
                Instant.now(), model, result, error);
    }
}
