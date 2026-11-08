package com.yolovision.repository;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.entity.ModelConfig;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.testcontainers.junit.jupiter.Testcontainers;

/** Executes real production migrations and database checks on disposable PostgreSQL 17. */
@DataJpaTest(showSql = false)
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@ActiveProfiles("postgres-test")
@Testcontainers
class PostgreSQLPersistenceIT extends AbstractRepositoryPersistenceTests {

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
    private Flyway flyway;

    @Test
    void productionMigrationsValidateAndRerunningDoesNotReapplySeeds() {
        assertThat(flyway.info().current().getVersion().getVersion()).isEqualTo("7");
        assertThat(flyway.info().applied()).hasSize(7);
        assertThat(flyway.info().pending()).isEmpty();
        assertThat(flyway.validateWithResult().validationSuccessful).isTrue();
        assertThat(flyway.migrate().migrationsExecuted).isZero();
        assertThat(jdbc.queryForObject(
                "SELECT count(*) FROM model_configs WHERE model_key = 'yolo26s'", Long.class))
                .isEqualTo(1L);
    }

    @Test
    void seededYolo26sMetadataIsNotAnAvailableModel() {
        ModelConfig model = models.findByModelKey("yolo26s").orElseThrow();

        assertThat(model.getVersion()).isEqualTo("YOLO26");
        assertThat(model.getModelSize()).isEqualTo("s");
        assertThat(model.getTaskType()).isEqualTo("DETECT");
        assertThat(model.getWeightsFilename()).isEqualTo("yolo26s.pt");
        assertThat(model.isEnabled()).isFalse();
        assertThat(models.findByEnabledTrueOrderByModelKeyAsc()).doesNotContain(model);
    }

    @Test
    void catalogMigrationRegistersExactlyTheTwentyApprovedDetectionModelsDisabled() {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT model_key, version, model_size, task_type, weights_filename, enabled
                FROM model_configs ORDER BY model_key
                """);
        Map<String, String> versions = Map.of(
                "yolov8", "YOLOv8", "yolo11", "YOLO11", "yolo12", "YOLO12", "yolo26", "YOLO26");

        assertThat(rows).hasSize(20);
        assertThat(rows).extracting(row -> row.get("model_key")).doesNotHaveDuplicates();
        for (String prefix : versions.keySet()) {
            for (String size : List.of("n", "s", "m", "l", "x")) {
                String key = prefix + size;
                assertThat(rows).as(key).anySatisfy(row -> {
                    assertThat(row.get("model_key")).isEqualTo(key);
                    assertThat(row.get("version")).isEqualTo(versions.get(prefix));
                    assertThat(row.get("model_size")).isEqualTo(size);
                    assertThat(row.get("task_type")).isEqualTo("DETECT");
                    assertThat(row.get("weights_filename")).isEqualTo(key + ".pt");
                    assertThat(row.get("enabled")).isEqualTo(false);
                });
            }
        }
        assertThat(models.findByEnabledTrueOrderByModelKeyAsc()).isEmpty();
    }

    @Test
    // Runs outside the per-test transaction: uncommitted setup rows would hold locks
    // that the migration's separate Flyway connection waits on indefinitely.
    @Transactional(propagation = Propagation.NOT_SUPPORTED)
    void catalogMigrationPreservesExistingRowsAdministratorChangesAndForeignKeys() {
        String schema = "phase04_upgrade_" + UUID.randomUUID().toString().replace("-", "");
        try {
            upgradeFromV5AndVerifyPreservation(schema);
        } finally {
            jdbc.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE");
        }
    }

    private void upgradeFromV5AndVerifyPreservation(String schema) {
        Flyway.configure().dataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword())
                .schemas(schema).createSchemas(true).target("5").load().migrate();
        UUID yolo26sId = jdbc.queryForObject(
                "UPDATE " + schema + ".model_configs SET enabled = TRUE, updated_at = TIMESTAMPTZ "
                        + "'2026-01-02 03:04:05+00' WHERE model_key = 'yolo26s' RETURNING id", UUID.class);
        UUID jobId = jdbc.queryForObject("INSERT INTO " + schema + ".detection_jobs "
                + "(model_id, video_url, confidence, image_size, selected_classes) "
                + "VALUES (?, 'https://example.com/video', 0.250, 960, '[2]'::jsonb) RETURNING id",
                UUID.class, yolo26sId);
        jdbc.update("INSERT INTO " + schema + ".model_configs "
                + "(model_key, version, model_size, task_type, weights_filename, enabled) "
                + "VALUES ('yolov8n', 'YOLOv8', 'n', 'DETECT', 'yolov8n.pt', TRUE)");

        int executed = Flyway.configure()
                .dataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword())
                .schemas(schema).target("6").load().migrate().migrationsExecuted;

        assertThat(executed).isEqualTo(1);
        Map<String, Object> yolo26s = jdbc.queryForMap("SELECT id, enabled, updated_at FROM " + schema
                + ".model_configs WHERE model_key = 'yolo26s'");
        assertThat(yolo26s.get("id")).isEqualTo(yolo26sId);
        assertThat(yolo26s.get("enabled")).isEqualTo(true);
        assertThat(yolo26s.get("updated_at").toString()).startsWith("2026-01-02");
        assertThat(jdbc.queryForObject("SELECT model_id FROM " + schema + ".detection_jobs WHERE id = ?",
                UUID.class, jobId)).isEqualTo(yolo26sId);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM " + schema + ".model_configs", Long.class))
                .isEqualTo(20L);
        assertThat(jdbc.queryForList("SELECT model_key FROM " + schema
                + ".model_configs WHERE enabled ORDER BY model_key", String.class))
                .containsExactly("yolo26s", "yolov8n");
    }

    // Each test ends with at most one expected violation: PostgreSQL aborts the transaction after it.
    @Test
    void messagingMigrationDefaultsExistingJobsToYoutubeAndRejectsUnknownSourceTypes() {
        DetectionJob job = persistedJob();
        assertColumnType("detection_job_outbox", "payload", "jsonb");
        assertColumnType("detection_results", "result_json_key", "text");
        assertThat(jdbc.queryForObject("SELECT source_type FROM detection_jobs WHERE id = ?", String.class,
                job.getId())).isEqualTo("YOUTUBE_URL");

        assertSqlState(() -> jdbc.update("UPDATE detection_jobs SET source_type = 'FTP' WHERE id = ?",
                job.getId()), "23514");
    }

    @Test
    void outboxAllowsOnlyOneExecutionCommandPerJob() {
        DetectionJob job = persistedJob();
        jdbc.update(OUTBOX_INSERT, UUID.randomUUID(), job.getId());
        assertThat(jdbc.queryForObject("SELECT status FROM detection_job_outbox WHERE job_id = ?", String.class,
                job.getId())).isEqualTo("PENDING");

        assertSqlState(() -> jdbc.update(OUTBOX_INSERT, UUID.randomUUID(), job.getId()), "23505");
    }

    @Test
    void outboxPayloadMustBeAJsonObject() {
        DetectionJob job = persistedJob();

        assertSqlState(() -> jdbc.update("""
                INSERT INTO detection_job_outbox (id, job_id, message_type, payload)
                VALUES (?, ?, 'other', '[]'::jsonb)
                """, UUID.randomUUID(), job.getId()), "23514");
    }

    private static final String OUTBOX_INSERT = """
            INSERT INTO detection_job_outbox (id, job_id, message_type, payload)
            VALUES (?, ?, 'detection.execute.v1', '{"jobId":"x"}'::jsonb)
            """;

    @Test
    void schemaUsesNativeJsonbTimestampsAndTheRequiredIndexes() {
        assertColumnType("detection_jobs", "selected_classes", "jsonb");
        assertColumnType("detection_results", "detection_summary", "jsonb");
        for (String table : List.of("model_configs", "detection_jobs", "detection_results")) {
            assertColumnType(table, "id", "uuid");
            assertColumnType(table, "created_at", "timestamptz");
        }
        assertColumnType("model_configs", "updated_at", "timestamptz");
        for (String column : List.of("updated_at", "started_at", "completed_at")) {
            assertColumnType("detection_jobs", column, "timestamptz");
        }
        assertThat(jdbc.queryForList(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()", String.class))
                .contains("uk_model_configs_model_key", "idx_detection_jobs_status",
                        "idx_detection_jobs_created_at", "idx_detection_jobs_model_id",
                        "idx_detection_jobs_status_created_at", "uk_detection_results_job_id");
        assertThat(jdbc.queryForObject(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_detection_jobs_status_created_at'",
                String.class)).contains("status, created_at DESC, id DESC");
    }

    @Test
    void sqlInsertsReceiveUuidTimestampStatusAndProgressDefaults() {
        UUID modelId = jdbc.queryForObject("""
                INSERT INTO model_configs (model_key, version, model_size, task_type, weights_filename)
                VALUES (?, 'TEST_VERSION', 's', 'DETECT', 'test-model.pt') RETURNING id
                """, UUID.class, "sql-default-" + UUID.randomUUID());
        assertThat(modelId).isNotNull();
        assertThat(jdbc.queryForObject("SELECT enabled FROM model_configs WHERE id = ?",
                Boolean.class, modelId)).isFalse();

        UUID jobId = jdbc.queryForObject("""
                INSERT INTO detection_jobs (model_id, video_url, confidence, image_size, selected_classes)
                VALUES (?, 'https://example.com/video', 0.450, 640, '[0, 2, 79]'::jsonb) RETURNING id
                """, UUID.class, modelId);
        Map<String, Object> job = jdbc.queryForMap(
                "SELECT status, progress, created_at, updated_at FROM detection_jobs WHERE id = ?", jobId);
        assertThat(jobId).isNotNull();
        assertThat(job).containsEntry("status", "PENDING").containsEntry("progress", 0);
        assertThat(job.get("created_at")).isNotNull();
        assertThat(job.get("updated_at")).isNotNull();

        UUID resultId = jdbc.queryForObject("""
                INSERT INTO detection_results (job_id, output_video_key, detection_summary)
                VALUES (?, 'results/output.mp4', '{}'::jsonb) RETURNING id
                """, UUID.class, jobId);
        Map<String, Object> result = jdbc.queryForMap("""
                SELECT input_video_key, total_frames, processing_time_ms, created_at
                FROM detection_results WHERE id = ?
                """, resultId);
        assertThat(resultId).isNotNull();
        assertThat(result.get("input_video_key")).isNull();
        assertThat(result.get("total_frames")).isNull();
        assertThat(result.get("processing_time_ms")).isNull();
        assertThat(result.get("created_at")).isNotNull();
    }

    @Test
    void jsonbValuesRemainQueryableAsAnArrayAndAnObject() {
        DetectionJob job = persistedJob();
        DetectionResult result = results.saveAndFlush(
                new DetectionResult(job, "results/output.mp4", Map.of("car", 120L, "person", 7L)));

        assertThat(jdbc.queryForObject(
                "SELECT jsonb_typeof(selected_classes) FROM detection_jobs WHERE id = ?",
                String.class, job.getId())).isEqualTo("array");
        assertThat(jdbc.queryForObject(
                "SELECT selected_classes ->> 4 FROM detection_jobs WHERE id = ?",
                String.class, job.getId())).isEqualTo("79");
        assertThat(jdbc.queryForObject(
                "SELECT jsonb_typeof(detection_summary) FROM detection_results WHERE id = ?",
                String.class, result.getId())).isEqualTo("object");
        assertThat(jdbc.queryForObject(
                "SELECT (detection_summary ->> 'car')::bigint FROM detection_results WHERE id = ?",
                Long.class, result.getId())).isEqualTo(120L);
    }

    @ParameterizedTest(name = "Database rejects {0}")
    @MethodSource("invalidJobValues")
    void databaseRejectsInvalidJobValuesEvenWithoutJpaValidation(String description, String assignment) {
        DetectionJob job = persistedJob();

        assertSqlState(() -> jdbc.update("UPDATE detection_jobs SET " + assignment + " WHERE id = ?",
                job.getId()), "23514");
    }

    static Stream<Arguments> invalidJobValues() {
        return Stream.of(
                Arguments.of("progress below zero", "progress = -1"),
                Arguments.of("progress above 100", "progress = 101"),
                Arguments.of("confidence below zero", "confidence = -0.001"),
                Arguments.of("confidence above one", "confidence = 1.001"),
                Arguments.of("zero image size", "image_size = 0"),
                Arguments.of("negative image size", "image_size = -32"),
                Arguments.of("unknown status", "status = 'UNRECOGNIZED'"),
                Arguments.of("selected classes object", "selected_classes = '{}'::jsonb"),
                Arguments.of("selected classes JSON null", "selected_classes = 'null'::jsonb"));
    }

    @ParameterizedTest(name = "Database rejects {0}")
    @MethodSource("invalidResultValues")
    void databaseRejectsInvalidResultMetadataEvenWithoutJpaValidation(String description, String assignment) {
        DetectionResult result = results.saveAndFlush(
                new DetectionResult(persistedJob(), "results/output.mp4", Map.of()));

        assertSqlState(() -> jdbc.update("UPDATE detection_results SET " + assignment + " WHERE id = ?",
                result.getId()), "23514");
    }

    static Stream<Arguments> invalidResultValues() {
        return Stream.of(
                Arguments.of("negative total frames", "total_frames = -1"),
                Arguments.of("negative processing time", "processing_time_ms = -1"),
                Arguments.of("summary array", "detection_summary = '[]'::jsonb"),
                Arguments.of("summary JSON null", "detection_summary = 'null'::jsonb"));
    }

    @Test
    void confidenceAndProgressBoundsAreInclusiveAndImageSizeIsConfigurable() {
        DetectionJob job = persistedJob();
        jdbc.update("""
                UPDATE detection_jobs SET confidence = 0.000, progress = 0, image_size = 320 WHERE id = ?
                """, job.getId());
        jdbc.update("""
                UPDATE detection_jobs SET confidence = 1.000, progress = 100, image_size = 1280 WHERE id = ?
                """, job.getId());
        entityManager.clear();

        DetectionJob reloaded = jobs.findById(job.getId()).orElseThrow();
        assertThat(reloaded.getConfidence()).isEqualByComparingTo("1.000");
        assertThat(reloaded.getProgress()).isEqualTo(100);
        assertThat(reloaded.getImageSize()).isEqualTo(1280);
    }

    @Test
    void databaseAcceptsEveryDeclaredStatusByName() {
        DetectionJob job = persistedJob();
        for (DetectionJobStatus status : DetectionJobStatus.values()) {
            jdbc.update("UPDATE detection_jobs SET status = ? WHERE id = ?", status.name(), job.getId());
            entityManager.clear();
            assertThat(jobs.findById(job.getId()).orElseThrow().getStatus()).isEqualTo(status);
        }
    }

    @Test
    void sqlCannotInsertAJobReferencingAMissingModel() {
        assertSqlState(() -> jdbc.update("""
                INSERT INTO detection_jobs (model_id, video_url, confidence, image_size, selected_classes)
                VALUES (?, 'https://example.com/video', 0.450, 640, '[]'::jsonb)
                """, UUID.randomUUID()), "23503");
    }

    @Test
    void sqlCannotInsertAResultReferencingAMissingJob() {
        assertSqlState(() -> jdbc.update("""
                INSERT INTO detection_results (job_id, output_video_key, detection_summary)
                VALUES (?, 'results/orphan.mp4', '{}'::jsonb)
                """, UUID.randomUUID()), "23503");
    }

    @Test
    void deletingAJobCascadesOnlyItsResultMetadataAndPreservesTheModel() {
        DetectionJob job = persistedJob();
        DetectionResult result = results.saveAndFlush(
                new DetectionResult(job, "results/output.mp4", Map.of("car", 3L)));
        UUID modelId = job.getModel().getId();

        jdbc.update("DELETE FROM detection_jobs WHERE id = ?", job.getId());
        entityManager.clear();

        assertThat(jobs.existsById(job.getId())).isFalse();
        assertThat(results.existsById(result.getId())).isFalse();
        assertThat(models.existsById(modelId)).isTrue();
    }

    private void assertColumnType(String table, String column, String expectedType) {
        assertThat(jdbc.queryForObject("""
                SELECT udt_name FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = ? AND column_name = ?
                """, String.class, table, column)).isEqualTo(expectedType);
    }

    private void assertSqlState(Runnable statement, String expectedState) {
        DataIntegrityViolationException error = assertThrows(
                DataIntegrityViolationException.class, statement::run);
        assertThat(error.getRootCause()).isInstanceOf(SQLException.class);
        assertThat(((SQLException) error.getRootCause()).getSQLState()).isEqualTo(expectedState);
    }
}
