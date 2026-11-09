package com.yolovision.controller;

import static org.assertj.core.api.Assertions.assertThat;

import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.entity.ModelConfig;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.DetectionResultRepository;
import com.yolovision.repository.ModelConfigRepository;
import io.minio.BucketExistsArgs;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import java.io.ByteArrayInputStream;
import java.math.BigDecimal;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

/**
 * Artifact delivery against real MinIO and PostgreSQL 17 through the real HTTP stack. Uses the
 * project's pinned MinIO image ({@code docker compose build minio} creates it; override with
 * {@code -Dminio.it.image=...}). Everything runs in disposable containers with random credentials.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("postgres-test")
@Testcontainers
class DetectionArtifactMinioIT {

    private static final String ACCESS_KEY = "it-" + UUID.randomUUID().toString().substring(0, 8);
    private static final String SECRET_KEY = UUID.randomUUID().toString();
    private static final String BUCKET = "videos-it";
    private static final int VIDEO_SIZE = 3 * 1024 * 1024 + 123;

    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:17-bookworm");

    @Container
    static final GenericContainer<?> MINIO = new GenericContainer<>(
            DockerImageName.parse(System.getProperty("minio.it.image", "yolo-vision-studio-minio:latest")))
            .withEnv("MINIO_ROOT_USER", ACCESS_KEY)
            .withEnv("MINIO_ROOT_PASSWORD", SECRET_KEY)
            .withCommand("server", "/data", "--address", ":9000")
            .withExposedPorts(9000)
            .waitingFor(Wait.forHttp("/minio/health/live").forPort(9000).withStartupTimeout(Duration.ofSeconds(60)));

    @DynamicPropertySource
    static void isolatedInfrastructure(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
        registry.add("app.storage.endpoint", DetectionArtifactMinioIT::minioEndpoint);
        registry.add("app.storage.access-key", () -> ACCESS_KEY);
        registry.add("app.storage.secret-key", () -> SECRET_KEY);
        registry.add("app.storage.bucket", () -> BUCKET);
    }

    @LocalServerPort
    private int port;

    @Autowired
    private ModelConfigRepository models;

    @Autowired
    private DetectionJobRepository jobs;

    @Autowired
    private DetectionResultRepository results;

    @Autowired
    private JdbcTemplate jdbc;

    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final byte[] video = new byte[VIDEO_SIZE];
    private MinioClient minio;
    private UUID jobId;
    private String manifest;

    @BeforeEach
    void storeArtifactsOfACompletedJob() throws Exception {
        jdbc.update("DELETE FROM detection_jobs");
        minio = MinioClient.builder().endpoint(minioEndpoint()).credentials(ACCESS_KEY, SECRET_KEY).build();
        if (!minio.bucketExists(BucketExistsArgs.builder().bucket(BUCKET).build())) {
            minio.makeBucket(MakeBucketArgs.builder().bucket(BUCKET).build()); // private by default
        }
        new Random(2026).nextBytes(video);
        ModelConfig model = models.findByModelKey("yolo11n").orElseThrow();
        DetectionJob job = new DetectionJob(model, "https://www.youtube.com/watch?v=abcdefghijk",
                new BigDecimal("0.250"), 640, List.of(1, 2, 3, 5, 7));
        job.setStatus(DetectionJobStatus.COMPLETED);
        job.setProgress(100);
        job = jobs.saveAndFlush(job);
        jobId = job.getId();
        manifest = """
                {"jobId": "%s", "modelKey": "yolo11n", "statistics": {"detectionsByClass": {"bus": 60}},
                 "artifacts": {"outputVideoKey": "%s", "resultJsonKey": "%s"}}"""
                .formatted(jobId, key("detected.mp4"), key("result.json"));
        put(key("detected.mp4"), video, "video/mp4");
        put(key("result.json"), manifest.getBytes(StandardCharsets.UTF_8), "application/json");
        DetectionResult result = new DetectionResult(job, key("detected.mp4"), Map.of("bus", 60L));
        result.setResultJsonKey(key("result.json"));
        results.saveAndFlush(result);
    }

    @AfterEach
    void removeOnlyThisTestsObjects() throws Exception {
        for (String name : List.of("detected.mp4", "result.json")) {
            minio.removeObject(RemoveObjectArgs.builder().bucket(BUCKET).object(key(name)).build());
        }
    }

    @Test
    void fullStreamAndDownloadReturnTheStoredObjectByteForByte() throws Exception {
        HttpResponse<byte[]> stream = get("/video", null);
        assertThat(stream.statusCode()).isEqualTo(200);
        assertThat(stream.headers().firstValue("Content-Type")).hasValue("video/mp4");
        assertThat(stream.headers().firstValueAsLong("Content-Length")).hasValue(VIDEO_SIZE);
        assertThat(stream.headers().firstValue("Accept-Ranges")).hasValue("bytes");
        assertThat(stream.headers().firstValue("ETag")).isPresent();
        assertThat(sha256(stream.body())).isEqualTo(sha256(video));

        HttpResponse<byte[]> download = get("/video/download", null);
        assertThat(download.statusCode()).isEqualTo(200);
        assertThat(download.headers().firstValue("Content-Disposition"))
                .hasValue("attachment; filename=\"detection-" + jobId + ".mp4\"");
        assertThat(sha256(download.body())).isEqualTo(sha256(video));
    }

    @ParameterizedTest
    @CsvSource({
        "bytes=0-1023, 0, 1023",
        "bytes=1048576-2097151, 1048576, 2097151",
        "bytes=3145800-, 3145800, 3145850",
        "bytes=-4096, 3141755, 3145850",
        "bytes=3145850-3145850, 3145850, 3145850",
        "bytes=3000000-9999999, 3000000, 3145850"
    })
    void rangesReturnExactSlicesOfTheStoredObject(String range, long start, long end) throws Exception {
        HttpResponse<byte[]> response = get("/video", range);

        assertThat(response.statusCode()).isEqualTo(206);
        assertThat(response.headers().firstValue("Content-Range"))
                .hasValue("bytes " + start + "-" + end + "/" + VIDEO_SIZE);
        assertThat(response.headers().firstValueAsLong("Content-Length")).hasValue(end - start + 1);
        assertThat(response.body()).isEqualTo(Arrays.copyOfRange(video, (int) start, (int) end + 1));
    }

    @Test
    void unsatisfiableRangeIs416WithTheRealSize() throws Exception {
        HttpResponse<byte[]> response = get("/video", "bytes=" + VIDEO_SIZE + "-");

        assertThat(response.statusCode()).isEqualTo(416);
        assertThat(response.headers().firstValue("Content-Range")).hasValue("bytes */" + VIDEO_SIZE);
    }

    @Test
    void resultJsonIsTheStoredArtifact() throws Exception {
        HttpResponse<byte[]> raw = get("/result.json", null);
        assertThat(raw.statusCode()).isEqualTo(200);
        assertThat(raw.headers().firstValue("Content-Type")).hasValue("application/json");
        assertThat(new String(raw.body(), StandardCharsets.UTF_8)).isEqualTo(manifest);

        HttpResponse<byte[]> download = get("/result.json/download", null);
        assertThat(download.headers().firstValue("Content-Disposition"))
                .hasValue("attachment; filename=\"detection-" + jobId + "-result.json\"");
        assertThat(download.body()).isEqualTo(raw.body());
    }

    @Test
    void aMissingObjectIsAControlled404() throws Exception {
        minio.removeObject(RemoveObjectArgs.builder().bucket(BUCKET).object(key("detected.mp4")).build());

        HttpResponse<byte[]> response = get("/video", null);
        assertThat(response.statusCode()).isEqualTo(404);
        String body = new String(response.body(), StandardCharsets.UTF_8);
        assertThat(body).contains("\"code\":\"ARTIFACT_NOT_FOUND\"").doesNotContain(BUCKET)
                .doesNotContain(MINIO.getHost() + ":" + MINIO.getMappedPort(9000));
    }

    @Test
    void theBucketStaysPrivate() throws Exception {
        HttpResponse<String> anonymous = http.send(HttpRequest.newBuilder(
                        URI.create(minioEndpoint() + "/" + BUCKET + "/" + key("detected.mp4"))).build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(anonymous.statusCode()).isEqualTo(403);
    }

    private HttpResponse<byte[]> get(String path, String range) throws Exception {
        HttpRequest.Builder request = HttpRequest.newBuilder(
                URI.create("http://127.0.0.1:" + port + "/api/v1/detections/" + jobId + path))
                .timeout(Duration.ofSeconds(30));
        if (range != null) {
            request.header("Range", range);
        }
        return http.send(request.build(), HttpResponse.BodyHandlers.ofByteArray());
    }

    private void put(String key, byte[] bytes, String contentType) throws Exception {
        minio.putObject(PutObjectArgs.builder().bucket(BUCKET).object(key)
                .stream(new ByteArrayInputStream(bytes), bytes.length, -1).contentType(contentType).build());
    }

    private String key(String name) {
        return "detections/" + jobId + "/" + name;
    }

    private static String minioEndpoint() {
        return "http://" + MINIO.getHost() + ":" + MINIO.getMappedPort(9000);
    }

    private static String sha256(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
}
