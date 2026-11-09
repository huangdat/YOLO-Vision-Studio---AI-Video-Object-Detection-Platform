package com.yolovision.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.entity.ModelConfig;
import com.yolovision.repository.DetectionJobOutboxRepository;
import com.yolovision.repository.DetectionJobRepository;
import com.yolovision.repository.DetectionResultRepository;
import com.yolovision.repository.ModelConfigRepository;
import com.yolovision.storage.InMemoryObjectStorage;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.math.BigDecimal;
import java.net.Socket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.test.context.ActiveProfiles;

/**
 * Transfer behaviour on a real embedded Tomcat, which MockMvc cannot show: an interrupted storage
 * read must abort the connection (never a short body reported as success), a client disconnect
 * must release the storage stream, and error responses stay problem+json for media requests.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
@Import(DetectionArtifactHttpTransferTest.Storage.class)
class DetectionArtifactHttpTransferTest {

    @TestConfiguration
    static class Storage {
        @Bean
        @Primary
        InMemoryObjectStorage inMemoryObjectStorage() {
            return new InMemoryObjectStorage();
        }
    }

    private static final int VIDEO_SIZE = 8 * 1024 * 1024;

    @LocalServerPort
    private int port;

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

    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final byte[] video = new byte[VIDEO_SIZE];
    private UUID jobId;

    @BeforeEach
    void completedJob() {
        cleanUp();
        new Random(7).nextBytes(video);
        ModelConfig model = new ModelConfig("yolo11n", "YOLO11", "n", "DETECT", "yolo11n.pt");
        model.setEnabled(true);
        model = models.saveAndFlush(model);
        DetectionJob job = new DetectionJob(model, "https://www.youtube.com/watch?v=abcdefghijk",
                new BigDecimal("0.250"), 640, List.of(2));
        job.setStatus(DetectionJobStatus.COMPLETED);
        job.setProgress(100);
        job = jobs.saveAndFlush(job);
        jobId = job.getId();
        String key = "detections/" + jobId + "/detected.mp4";
        results.saveAndFlush(new DetectionResult(job, key, Map.of("car", 3L)));
        storage.put(key, video, "video/mp4");
    }

    @AfterEach
    void cleanUp() {
        storage.reset();
        results.deleteAll();
        outbox.deleteAll();
        jobs.deleteAll();
        models.deleteAll();
    }

    @Test
    void completeAndRangedTransfersMatchTheStoredBytes() throws Exception {
        HttpResponse<byte[]> full = http.send(request("/video").build(), HttpResponse.BodyHandlers.ofByteArray());
        assertThat(full.statusCode()).isEqualTo(200);
        assertThat(full.headers().firstValueAsLong("Content-Length")).hasValue(VIDEO_SIZE);
        assertThat(full.body()).isEqualTo(video);

        HttpResponse<byte[]> range = http.send(request("/video").header("Range", "bytes=4194304-4195327").build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertThat(range.statusCode()).isEqualTo(206);
        assertThat(range.headers().firstValue("Content-Range")).hasValue("bytes 4194304-4195327/" + VIDEO_SIZE);
        assertThat(range.body()).isEqualTo(java.util.Arrays.copyOfRange(video, 4194304, 4195328));
    }

    @Test
    void aStorageFailureMidTransferIsVisibleToTheClient() throws Exception {
        storage.failStreamsAfter(1024 * 1024);

        assertThatThrownBy(() -> http.send(request("/video/download").build(), HttpResponse.BodyHandlers.ofByteArray()))
                .isInstanceOf(IOException.class);
        assertThat(storage.opens()).singleElement().satisfies(open -> assertThat(open.closed()).isTrue());

        // The server keeps serving afterwards.
        storage.failStreamsAfter(-1);
        HttpResponse<byte[]> retry = http.send(request("/video").header("Range", "bytes=0-99").build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertThat(retry.statusCode()).isEqualTo(206);
    }

    @Test
    void aClientDisconnectReleasesTheStorageStream() throws Exception {
        try (Socket socket = new Socket("127.0.0.1", port)) {
            OutputStream out = socket.getOutputStream();
            out.write(("GET /api/v1/detections/" + jobId + "/video HTTP/1.1\r\nHost: localhost\r\n\r\n")
                    .getBytes(StandardCharsets.US_ASCII));
            out.flush();
            InputStream in = socket.getInputStream();
            assertThat(in.readNBytes(4096)).hasSize(4096); // headers and the first bytes of the video
        }
        long deadline = System.nanoTime() + Duration.ofSeconds(10).toNanos();
        while (System.nanoTime() < deadline
                && !(storage.opens().size() == 1 && storage.opens().get(0).closed().get())) {
            Thread.sleep(50);
        }
        assertThat(storage.opens()).singleElement().satisfies(open -> assertThat(open.closed()).isTrue());

        HttpResponse<byte[]> next = http.send(request("/video").header("Range", "bytes=-10").build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertThat(next.statusCode()).isEqualTo(206);
        assertThat(next.body()).hasSize(10);
    }

    @Test
    void errorsAreProblemJsonEvenForMediaAcceptHeaders() throws Exception {
        HttpResponse<String> response = http.send(
                HttpRequest.newBuilder(URI.create(base() + UUID.randomUUID() + "/video"))
                        .header("Accept", "video/mp4").build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(404);
        assertThat(response.headers().firstValue("Content-Type")).hasValueSatisfying(
                type -> assertThat(type).startsWith("application/problem+json"));
        assertThat(response.body()).contains("\"code\":\"JOB_NOT_FOUND\"").doesNotContain("<html");

        HttpResponse<String> unsatisfiable = http.send(request("/video").header("Accept", "*/*")
                .header("Range", "bytes=" + VIDEO_SIZE + "-").build(), HttpResponse.BodyHandlers.ofString());
        assertThat(unsatisfiable.statusCode()).isEqualTo(416);
        assertThat(unsatisfiable.headers().firstValue("Content-Range")).hasValue("bytes */" + VIDEO_SIZE);
    }

    private HttpRequest.Builder request(String path) {
        return HttpRequest.newBuilder(URI.create(base() + jobId + path)).timeout(Duration.ofSeconds(30));
    }

    private String base() {
        return "http://127.0.0.1:" + port + "/api/v1/detections/";
    }
}
