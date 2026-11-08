package com.yolovision.messaging;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yolovision.config.MessagingProperties;
import com.yolovision.dto.DetectionJobSubmissionRequest;
import com.yolovision.entity.DetectionSourceType;
import com.yolovision.service.DetectionJobSubmissionService;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

/**
 * Real PostgreSQL 17 and RabbitMQ 4.2: outbox publication with confirms, the event
 * listener, dead-lettering, and idempotent completion. The worker side is simulated by
 * publishing contract-conformant events; the Python worker has its own broker tests.
 */
@SpringBootTest(properties = {
    "spring.rabbitmq.listener.simple.auto-startup=true",
    "spring.rabbitmq.listener.simple.retry.initial-interval=100ms",
    "app.messaging.outbox.enabled=true",
    "app.messaging.outbox.poll-interval=200ms"
})
@ActiveProfiles("postgres-test")
@Testcontainers
class DetectionMessagingPostgreSQLIT {

    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:17-bookworm");

    @Container
    static final GenericContainer<?> RABBITMQ = new GenericContainer<>("rabbitmq:4.2-management")
            .withEnv("RABBITMQ_DEFAULT_USER", "it-user")
            .withEnv("RABBITMQ_DEFAULT_PASS", "it-password")
            .withExposedPorts(5672)
            .waitingFor(Wait.forLogMessage(".*Server startup complete.*\\n", 1))
            .withStartupTimeout(Duration.ofMinutes(2));

    @DynamicPropertySource
    static void infrastructure(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
        registry.add("spring.rabbitmq.host", RABBITMQ::getHost);
        registry.add("spring.rabbitmq.port", () -> RABBITMQ.getMappedPort(5672));
        registry.add("spring.rabbitmq.username", () -> "it-user");
        registry.add("spring.rabbitmq.password", () -> "it-password");
    }

    @Autowired
    private DetectionJobSubmissionService submissions;

    @Autowired
    private RabbitTemplate rabbitTemplate;

    @Autowired
    private MessagingProperties messaging;

    @Autowired
    private JdbcTemplate jdbc;

    @Autowired
    private ObjectMapper objectMapper;

    @BeforeEach
    void enableOneModelAsAnAdministratorWould() {
        jdbc.update("UPDATE model_configs SET enabled = (model_key = 'yolo11n')");
    }

    @Test
    void topologyIsDurableQuorumQueuesWithDeliveryLimitsAndDeadLettering() throws Exception {
        var result = RABBITMQ.execInContainer("rabbitmqctl", "-q", "list_queues", "name", "type", "durable",
                "arguments");
        String queues = result.getStdout();

        assertThat(queues).contains(messaging.commandQueue(), messaging.eventQueue(), messaging.deadLetterQueue());
        for (String line : queues.lines().filter(line -> line.startsWith("vision.detection.")).toList()) {
            assertThat(line).as(line).contains("quorum").contains("true");
        }
        String jobs = queues.lines().filter(line -> line.startsWith(messaging.commandQueue() + "\t"))
                .findFirst().orElseThrow();
        assertThat(jobs).contains("x-delivery-limit").contains(messaging.deadLetterExchange());
    }

    @Test
    void submittedJobIsPublishedWithConfirmAndThenMarkedQueued() throws Exception {
        UUID jobId = submit();

        awaitStatus(jobId, "QUEUED");
        assertThat(jdbc.queryForObject("SELECT status FROM detection_job_outbox WHERE job_id = ?",
                String.class, jobId)).isEqualTo("PUBLISHED");

        Message command = receiveCommandFor(jobId);
        assertThat(command.getMessageProperties().getReceivedDeliveryMode()).isEqualTo(MessageDeliveryMode.PERSISTENT);
        assertThat(command.getMessageProperties().getContentType()).isEqualTo("application/json");
        JsonNode body = objectMapper.readTree(command.getBody());
        assertThat(command.getMessageProperties().getMessageId()).isEqualTo(body.get("messageId").asText());
        assertThat(body.get("schemaVersion").asInt()).isEqualTo(1);
        assertThat(body.get("modelKey").asText()).isEqualTo("yolo11n");
        assertThat(body.get("sourceType").asText()).isEqualTo("LOCAL_FILE");
        assertThat(body.get("source").asText()).isEqualTo("fixtures/clip.mp4");
        assertThat(body.get("imageSize").asInt()).isEqualTo(320);
        assertThat(body.get("classes").toString()).isEqualTo("[1,2,3,5,7]");
    }

    @Test
    void workerEventsDriveTheJobToCompletionIdempotently() throws Exception {
        UUID jobId = submit();
        awaitStatus(jobId, "QUEUED");

        sendEvent(event(jobId, "DOWNLOADING", 3, null, null));
        sendEvent(event(jobId, "DETECTING", 50, null, null));
        awaitProgress(jobId, "DETECTING", 50);
        sendEvent(event(jobId, "DETECTING", 30, null, null));
        sendEvent(event(jobId, "ENCODING", 90, null, null));
        sendEvent(event(jobId, "UPLOADING", 96, null, null));
        String completion = event(jobId, "COMPLETED", 100, "yolo11n", null);
        sendEvent(completion);
        sendEvent(completion);
        sendEvent(event(jobId, "DETECTING", 60, null, null));

        awaitStatus(jobId, "COMPLETED");
        awaitEventQueueDrained();
        Map<String, Object> job = jdbc.queryForMap(
                "SELECT status, progress, started_at, completed_at FROM detection_jobs WHERE id = ?", jobId);
        assertThat(job).containsEntry("status", "COMPLETED").containsEntry("progress", 100);
        assertThat(job.get("started_at")).isNotNull();
        assertThat(job.get("completed_at")).isNotNull();
        Map<String, Object> result = jdbc.queryForMap("""
                SELECT output_video_key, result_json_key, total_frames, processing_time_ms,
                       (detection_summary ->> 'bus')::bigint AS buses, jsonb_typeof(detection_summary) AS type
                FROM detection_results WHERE job_id = ?
                """, jobId);
        assertThat(result).containsEntry("output_video_key", "detections/" + jobId + "/detected.mp4")
                .containsEntry("result_json_key", "detections/" + jobId + "/result.json")
                .containsEntry("total_frames", 36).containsEntry("processing_time_ms", 7058L)
                .containsEntry("buses", 36L).containsEntry("type", "object");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM detection_results WHERE job_id = ?", Long.class, jobId))
                .isEqualTo(1L);
    }

    @Test
    void failureEventMarksTheJobFailedWithItsErrorCode() {
        UUID jobId = submit();
        awaitStatus(jobId, "QUEUED");

        sendEvent(event(jobId, "FAILED", 12, null, "{\"code\":\"VIDEO_DOWNLOAD_FAILED\","
                + "\"message\":\"The YouTube video could not be downloaded.\",\"retryable\":false}"));

        awaitStatus(jobId, "FAILED");
        assertThat(jdbc.queryForMap("SELECT error_code, error_message FROM detection_jobs WHERE id = ?", jobId))
                .containsEntry("error_code", "VIDEO_DOWNLOAD_FAILED")
                .containsEntry("error_message", "The YouTube video could not be downloaded.");
    }

    @Test
    void malformedEventsAndUnknownJobsAreDeadLetteredNotRetriedForever() {
        String malformedMarker = "malformed-" + UUID.randomUUID();
        UUID unknownJob = UUID.randomUUID();

        sendEvent("{\"not\":\"" + malformedMarker + "\"");
        sendEvent(event(unknownJob, "DETECTING", 10, null, null));

        List<String> deadLetters = new ArrayList<>();
        await(() -> {
            Message message = rabbitTemplate.receive(messaging.deadLetterQueue(), 500);
            if (message != null) {
                deadLetters.add(new String(message.getBody(), StandardCharsets.UTF_8));
            }
            return deadLetters.stream().anyMatch(body -> body.contains(malformedMarker))
                    && deadLetters.stream().anyMatch(body -> body.contains(unknownJob.toString()));
        }, Duration.ofSeconds(20));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM detection_jobs WHERE id = ?", Long.class, unknownJob))
                .isZero();
    }

    private UUID submit() {
        return submissions.submit(new DetectionJobSubmissionRequest("yolo11n", DetectionSourceType.LOCAL_FILE,
                "fixtures/clip.mp4", null, 320, null));
    }

    private String event(UUID jobId, String status, int progress, String modelKey, String error) {
        String result = !"COMPLETED".equals(status) ? "" : ",\"result\":{\"outputVideoKey\":\"detections/" + jobId
                + "/detected.mp4\",\"resultJsonKey\":\"detections/" + jobId + "/result.json\",\"totalFrames\":36,"
                + "\"processingTimeMs\":7058,\"detectionSummary\":{\"bus\":36}}";
        return "{\"schemaVersion\":1,\"eventId\":\"" + UUID.randomUUID() + "\",\"jobId\":\"" + jobId
                + "\",\"status\":\"" + status + "\",\"progress\":" + progress + ",\"timestamp\":\""
                + Instant.now() + "\"" + (modelKey == null ? "" : ",\"modelKey\":\"" + modelKey + "\"")
                + result + (error == null ? "" : ",\"error\":" + error) + "}";
    }

    private void sendEvent(String json) {
        rabbitTemplate.send(messaging.eventExchange(), messaging.eventRoutingKey(),
                MessageBuilder.withBody(json.getBytes(StandardCharsets.UTF_8)).setContentType("application/json")
                        .setDeliveryMode(MessageDeliveryMode.PERSISTENT).build());
    }

    private Message receiveCommandFor(UUID jobId) {
        Message[] found = new Message[1];
        await(() -> {
            Message message = rabbitTemplate.receive(messaging.commandQueue(), 500);
            if (message != null && jobId.toString().equals(message.getMessageProperties().getCorrelationId())) {
                found[0] = message;
            }
            return found[0] != null;
        }, Duration.ofSeconds(15));
        return found[0];
    }

    private void awaitStatus(UUID jobId, String status) {
        await(() -> status.equals(jdbc.queryForObject("SELECT status FROM detection_jobs WHERE id = ?",
                String.class, jobId)), Duration.ofSeconds(20));
    }

    private void awaitProgress(UUID jobId, String status, int progress) {
        await(() -> jdbc.queryForMap("SELECT status, progress FROM detection_jobs WHERE id = ?", jobId)
                .equals(Map.of("status", status, "progress", progress)), Duration.ofSeconds(20));
    }

    private void awaitEventQueueDrained() throws Exception {
        await(() -> {
            try {
                String out = RABBITMQ.execInContainer("rabbitmqctl", "-q", "list_queues", "name", "messages")
                        .getStdout();
                return out.lines().anyMatch(line -> line.equals(messaging.eventQueue() + "\t0"));
            } catch (Exception exception) {
                return false;
            }
        }, Duration.ofSeconds(20));
    }

    private static void await(Supplier<Boolean> condition, Duration timeout) {
        Instant deadline = Instant.now().plus(timeout);
        while (Instant.now().isBefore(deadline)) {
            if (Boolean.TRUE.equals(condition.get())) {
                return;
            }
            try {
                Thread.sleep(100);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                throw new AssertionError(exception);
            }
        }
        throw new AssertionError("Condition not met within " + timeout);
    }
}
