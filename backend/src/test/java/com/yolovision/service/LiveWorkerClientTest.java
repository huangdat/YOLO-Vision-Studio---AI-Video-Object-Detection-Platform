package com.yolovision.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import com.yolovision.config.LiveDetectionProperties;
import com.yolovision.dto.live.LiveMessages.WorkerResult;
import com.yolovision.service.LiveWorkerClient.LiveWorkerException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.CompletionException;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

class LiveWorkerClientTest {

    private HttpServer server;
    private LiveWorkerClient client;
    private final AtomicReference<String> lastQuery = new AtomicReference<>();
    private final AtomicReference<String> lastType = new AtomicReference<>();
    private final AtomicReference<Integer> lastBodyLength = new AtomicReference<>();

    private void start(int status, String body, long delayMillis) throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/live", exchange -> {
            lastQuery.set(exchange.getRequestURI().getRawPath() + "?" + exchange.getRequestURI().getRawQuery());
            lastType.set(exchange.getRequestHeaders().getFirst("Content-Type"));
            lastBodyLength.set(exchange.getRequestBody().readAllBytes().length);
            try {
                Thread.sleep(delayMillis);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            }
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.start();
        client = client("http://127.0.0.1:" + server.getAddress().getPort(), Duration.ofSeconds(2));
    }

    private static LiveWorkerClient client(String url, Duration timeout) {
        return new LiveWorkerClient(new LiveDetectionProperties(url, 1, 5, 1024, List.of(320, 416, 640),
                List.of("n"), timeout, timeout, Duration.ofSeconds(30), Duration.ofMinutes(30),
                Duration.ofSeconds(5)), new ObjectMapper());
    }

    @AfterEach
    void stop() {
        if (server != null) {
            server.stop(0);
        }
        if (client != null) {
            client.shutdown();
        }
    }

    @Test
    void inferSendsRawJpegWithTheSessionSettingsAndParsesTheContract() throws Exception {
        start(200, """
                {"frameId":42,"modelKey":"yolo11n","width":640,"height":480,
                 "detections":[{"classId":2,"label":"car","confidence":0.87,"box":[120,85,310,260]}],"inferenceMs":85.0}
                """, 0);

        WorkerResult result = client.infer(new byte[] {(byte) 0xFF, (byte) 0xD8, 1, 2}, 42, "yolo11n", "0.3", 416,
                List.of(1, 2, 7)).join();

        assertThat(lastQuery.get()).isEqualTo(
                "/internal/live/infer?modelKey=yolo11n&frameId=42&confidence=0.3&imageSize=416&classes=1,2,7");
        assertThat(lastType.get()).isEqualTo("image/jpeg");
        assertThat(lastBodyLength.get()).isEqualTo(4);
        assertThat(result.frameId()).isEqualTo(42);
        assertThat(result.detections()).singleElement().satisfies(d -> {
            assertThat(d.label()).isEqualTo("car");
            assertThat(d.box()).containsExactly(120.0, 85.0, 310.0, 260.0);
        });
    }

    @Test
    void loadRequestsTheModelAtTheSessionImageSize() throws Exception {
        start(200, "{\"modelKey\":\"yolo11n\",\"device\":\"cpu\",\"classes\":80}", 0);
        assertThat(client.load("yolo11n", 320).join().device()).isEqualTo("cpu");
        assertThat(lastQuery.get()).isEqualTo("/internal/live/models/yolo11n/load?imageSize=320");
    }

    @ParameterizedTest
    @CsvSource({"409,MODEL_NOT_PREPARED", "404,MODEL_NOT_SUPPORTED", "400,INVALID_FRAME", "413,FRAME_TOO_LARGE",
        "500,INFERENCE_FAILED", "503,MODEL_LOAD_FAILED", "429,WORKER_BUSY"})
    void workerErrorCodesArePreserved(int status, String code) throws Exception {
        start(status, "{\"error\":{\"code\":\"" + code + "\",\"message\":\"detail\"}}", 0);
        assertThatThrownBy(() -> client.infer(new byte[] {1}, 1, "yolo11n", "0.25", 416, List.of(2)).join())
                .isInstanceOf(CompletionException.class)
                .cause().isInstanceOf(LiveWorkerException.class)
                .extracting(error -> ((LiveWorkerException) error).getCode()).isEqualTo(code);
    }

    @Test
    void unknownErrorsBecomeWorkerUnavailable() throws Exception {
        start(502, "<html>bad gateway</html>", 0);
        assertThatThrownBy(() -> client.load("yolo11n", 416).join())
                .cause().extracting(error -> ((LiveWorkerException) error).getCode()).isEqualTo("WORKER_UNAVAILABLE");
    }

    @Test
    void anUnreachableWorkerIsUnavailableWithoutLeakingTheAddress() throws Exception {
        int closed;
        try (ServerSocket socket = new ServerSocket(0)) {
            closed = socket.getLocalPort();
        }
        client = client("http://127.0.0.1:" + closed, Duration.ofSeconds(2));
        assertThatThrownBy(() -> client.infer(new byte[] {1}, 1, "yolo11n", "0.25", 416, List.of(2)).join())
                .cause().isInstanceOf(LiveWorkerException.class)
                .satisfies(error -> {
                    assertThat(((LiveWorkerException) error).getCode()).isEqualTo("WORKER_UNAVAILABLE");
                    assertThat(error.getMessage()).doesNotContain("127.0.0.1");
                });
    }

    @Test
    void aSlowWorkerTimesOut() throws Exception {
        start(200, "{}", 1_500);
        client = client("http://127.0.0.1:" + server.getAddress().getPort(), Duration.ofMillis(300));
        assertThatThrownBy(() -> client.infer(new byte[] {1}, 1, "yolo11n", "0.25", 416, List.of(2)).join())
                .cause().extracting(error -> ((LiveWorkerException) error).getCode()).isEqualTo("INFERENCE_TIMEOUT");
    }

    @Test
    void anUnreadableSuccessResponseIsAnInferenceFailure() throws Exception {
        start(200, "not json", 0);
        assertThatThrownBy(() -> client.infer(new byte[] {1}, 1, "yolo11n", "0.25", 416, List.of(2)).join())
                .cause().extracting(error -> ((LiveWorkerException) error).getCode()).isEqualTo("INFERENCE_FAILED");
    }
}
