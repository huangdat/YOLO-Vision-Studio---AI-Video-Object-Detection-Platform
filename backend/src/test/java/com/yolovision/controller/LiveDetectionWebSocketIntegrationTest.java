package com.yolovision.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import com.yolovision.entity.ModelConfig;
import com.yolovision.repository.ModelConfigRepository;
import com.yolovision.service.LiveDetectionService;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.web.socket.BinaryMessage;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketHttpHeaders;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.client.standard.StandardWebSocketClient;
import org.springframework.web.socket.handler.AbstractWebSocketHandler;

/** The Live Detection WebSocket on real embedded Tomcat, with a fake internal worker. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
class LiveDetectionWebSocketIntegrationTest {

    private static final HttpServer WORKER = fakeWorker();
    private static final Pattern FRAME_ID = Pattern.compile("frameId=(\\d+)");
    private static volatile String loadBody = "{\"modelKey\":\"yolo11n\",\"device\":\"cpu\",\"classes\":80}";
    private static volatile int loadStatus = 200;

    @DynamicPropertySource
    static void liveWorker(DynamicPropertyRegistry registry) {
        registry.add("app.live.worker-url", () -> "http://127.0.0.1:" + WORKER.getAddress().getPort());
        registry.add("app.live.max-frame-bytes", () -> 4096);
    }

    @LocalServerPort
    private int port;

    @Autowired
    private ModelConfigRepository models;

    @Autowired
    private LiveDetectionService service;

    private final ObjectMapper mapper = new ObjectMapper();

    private static HttpServer fakeWorker() {
        try {
            HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/internal/live/models", exchange -> {
                byte[] body = loadBody.getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(loadStatus, body.length);
                exchange.getResponseBody().write(body);
                exchange.close();
            });
            server.createContext("/internal/live/infer", exchange -> {
                exchange.getRequestBody().readAllBytes();
                Matcher matcher = FRAME_ID.matcher(exchange.getRequestURI().getRawQuery());
                String frameId = matcher.find() ? matcher.group(1) : "0";
                byte[] body = ("{\"frameId\":" + frameId + ",\"modelKey\":\"yolo11n\",\"width\":640,\"height\":480,"
                        + "\"detections\":[{\"classId\":0,\"label\":\"person\",\"confidence\":0.9,"
                        + "\"box\":[10,20,110,220]}],\"inferenceMs\":31.5}").getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(200, body.length);
                exchange.getResponseBody().write(body);
                exchange.close();
            });
            server.start();
            return server;
        } catch (Exception exception) {
            throw new IllegalStateException(exception);
        }
    }

    @AfterAll
    static void stopWorker() {
        WORKER.stop(0);
    }

    @BeforeEach
    void enabledModel() {
        models.findByModelKey("yolo11n").ifPresent(models::delete);
        ModelConfig model = new ModelConfig("yolo11n", "YOLO11", "n", "DETECT", "yolo11n.pt");
        model.setEnabled(true);
        models.saveAndFlush(model);
        loadStatus = 200;
        loadBody = "{\"modelKey\":\"yolo11n\",\"device\":\"cpu\",\"classes\":80}";
    }

    @AfterEach
    void cleanUp() {
        models.findByModelKey("yolo11n").ifPresent(models::delete);
    }

    static final class Recorder extends AbstractWebSocketHandler {
        final BlockingQueue<String> messages = new LinkedBlockingQueue<>();
        final CompletableFuture<CloseStatus> closed = new CompletableFuture<>();

        @Override
        protected void handleTextMessage(WebSocketSession session, TextMessage message) {
            messages.add(message.getPayload());
        }

        @Override
        public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
            closed.complete(status);
        }
    }

    private WebSocketSession connect(Recorder recorder, String origin) throws Exception {
        WebSocketHttpHeaders headers = new WebSocketHttpHeaders();
        if (origin != null) {
            headers.setOrigin(origin);
        }
        StandardWebSocketClient client = new StandardWebSocketClient();
        return client.execute(recorder, headers, URI.create("ws://localhost:" + port + "/api/v1/live/ws"))
                .get(5, TimeUnit.SECONDS);
    }

    private JsonNode next(Recorder recorder) throws Exception {
        String message = recorder.messages.poll(5, TimeUnit.SECONDS);
        assertThat(message).as("expected a message").isNotNull();
        return mapper.readTree(message);
    }

    private static BinaryMessage frame(long frameId, int bytes) {
        ByteBuffer buffer = ByteBuffer.allocate(4 + bytes);
        buffer.putInt((int) frameId).put(new byte[bytes]).flip();
        return new BinaryMessage(buffer);
    }

    private static TextMessage start() {
        return new TextMessage("{\"type\":\"start\",\"version\":1,\"modelKey\":\"yolo11n\",\"imageSize\":416,"
                + "\"classes\":[0,2]}");
    }

    @Test
    void aFullSessionFromAnAllowedOrigin() throws Exception {
        Recorder recorder = new Recorder();
        WebSocketSession session = connect(recorder, "http://localhost:5173");

        session.sendMessage(start());
        JsonNode ready = next(recorder);
        assertThat(ready.path("type").asText()).isEqualTo("ready");
        assertThat(ready.path("maxFrameBytes").asInt()).isEqualTo(4096);

        session.sendMessage(frame(7, 1000));
        JsonNode detections = next(recorder);
        assertThat(detections.path("type").asText()).isEqualTo("detections");
        assertThat(detections.path("frameId").asLong()).isEqualTo(7);
        assertThat(detections.path("detections").get(0).path("label").asText()).isEqualTo("person");
        assertThat(detections.path("inferenceMs").asDouble()).isEqualTo(31.5);
        assertThat(detections.path("serverMs").asLong()).isGreaterThanOrEqualTo(0);

        session.sendMessage(new TextMessage("{\"type\":\"stop\"}"));
        JsonNode stopped = next(recorder);
        assertThat(stopped.path("type").asText()).isEqualTo("stopped");
        assertThat(stopped.path("processedFrames").asLong()).isEqualTo(1);
        assertThat(recorder.closed.get(5, TimeUnit.SECONDS).getCode()).isEqualTo(1000);
        awaitNoActiveSessions();
    }

    @Test
    void sameOriginRequestsAreAllowed() throws Exception {
        Recorder recorder = new Recorder();
        WebSocketSession session = connect(recorder, "http://localhost:" + port);
        session.sendMessage(start());
        assertThat(next(recorder).path("type").asText()).isEqualTo("ready");
        session.close();
        awaitNoActiveSessions();
    }

    @Test
    void foreignOriginsAreRejectedAtTheHandshake() {
        assertThatThrownBy(() -> connect(new Recorder(), "https://evil.example"))
                .hasStackTraceContaining("403");
        assertThat(service.activeSessions()).isZero();
    }

    @Test
    void framesLargerThanTheTransportLimitCloseTheConnection() throws Exception {
        Recorder recorder = new Recorder();
        WebSocketSession session = connect(recorder, "http://localhost:5173");
        session.sendMessage(start());
        next(recorder);

        session.sendMessage(frame(1, 4096 + 2048));
        assertThat(recorder.closed.get(5, TimeUnit.SECONDS).getCode()).isEqualTo(1009);
        awaitNoActiveSessions();
    }

    @Test
    void anUnpreparedModelIsAFatalErrorAndAClientDisconnectFreesTheSlot() throws Exception {
        loadStatus = 409;
        loadBody = "{\"error\":{\"code\":\"MODEL_NOT_PREPARED\",\"message\":\"yolo11n.pt is not prepared.\"}}";
        Recorder failing = new Recorder();
        WebSocketSession first = connect(failing, "http://localhost:5173");
        first.sendMessage(start());
        JsonNode error = next(failing);
        assertThat(error.path("code").asText()).isEqualTo("MODEL_NOT_PREPARED");
        assertThat(error.path("fatal").asBoolean()).isTrue();
        assertThat(failing.closed.get(5, TimeUnit.SECONDS).getCode()).isEqualTo(1008);

        loadStatus = 200;
        loadBody = "{\"modelKey\":\"yolo11n\",\"device\":\"cpu\",\"classes\":80}";
        Recorder recorder = new Recorder();
        WebSocketSession second = connect(recorder, "http://localhost:5173");
        second.sendMessage(start());
        assertThat(next(recorder).path("type").asText()).isEqualTo("ready");
        second.close(CloseStatus.GOING_AWAY); // abrupt client exit
        awaitNoActiveSessions();
    }

    private void awaitNoActiveSessions() throws InterruptedException {
        for (int i = 0; i < 50 && service.activeSessions() > 0; i++) {
            Thread.sleep(100);
        }
        assertThat(service.activeSessions()).isZero();
    }
}
