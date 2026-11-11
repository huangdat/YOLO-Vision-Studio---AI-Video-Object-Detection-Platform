package com.yolovision.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yolovision.config.LiveDetectionProperties;
import com.yolovision.service.LiveDetectionService;
import com.yolovision.service.LiveDetectionService.LiveConnection;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.BinaryMessage;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.AbstractWebSocketHandler;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;

/**
 * WebSocket adapter for Live Detection ({@code /api/v1/live/ws}). It only translates transport
 * events; all rules live in {@link LiveDetectionService}. Outgoing messages go through a
 * {@link ConcurrentWebSocketSessionDecorator}, so worker callbacks can send safely with a
 * bounded send time and buffer.
 */
@Component
public class LiveDetectionWebSocketHandler extends AbstractWebSocketHandler {

    private static final Logger LOG = LoggerFactory.getLogger(LiveDetectionWebSocketHandler.class);
    private static final int TEXT_LIMIT = 8 * 1024;
    private static final int SEND_BUFFER_LIMIT = 512 * 1024;

    private final LiveDetectionService service;
    private final LiveDetectionProperties properties;
    private final ObjectMapper objectMapper;
    private final Map<String, Connection> connections = new ConcurrentHashMap<>();

    public LiveDetectionWebSocketHandler(LiveDetectionService service, LiveDetectionProperties properties,
            ObjectMapper objectMapper) {
        this.service = service;
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        // Transport limits: larger messages are rejected by the container (close 1009).
        session.setTextMessageSizeLimit(TEXT_LIMIT);
        session.setBinaryMessageSizeLimit(properties.maxFrameBytes() + 4);
        Connection connection = new Connection(new ConcurrentWebSocketSessionDecorator(session,
                (int) properties.sendTimeLimit().toMillis(), SEND_BUFFER_LIMIT), objectMapper);
        connections.put(session.getId(), connection);
        service.opened(connection);
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        Connection connection = connections.get(session.getId());
        if (connection != null) {
            service.text(connection, message.getPayload());
        }
    }

    @Override
    protected void handleBinaryMessage(WebSocketSession session, BinaryMessage message) {
        Connection connection = connections.get(session.getId());
        if (connection != null) {
            service.binary(connection, message.getPayload());
        }
    }

    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) {
        LOG.debug("Live WebSocket transport error: {}", exception.getClass().getSimpleName());
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        Connection connection = connections.remove(session.getId());
        if (connection != null) {
            service.closed(connection);
        }
    }

    @Override
    public boolean supportsPartialMessages() {
        return false;
    }

    private record Connection(WebSocketSession session, ObjectMapper objectMapper) implements LiveConnection {

        @Override
        public String id() {
            return session.getId();
        }

        @Override
        public boolean isOpen() {
            return session.isOpen();
        }

        @Override
        public void send(Object message) {
            if (!session.isOpen()) {
                return;
            }
            try {
                session.sendMessage(new TextMessage(objectMapper.writeValueAsString(message)));
            } catch (IOException | IllegalStateException exception) {
                LOG.debug("Could not send a live message: {}", exception.getClass().getSimpleName());
            }
        }

        @Override
        public void close(int code, String reason) {
            if (!session.isOpen()) {
                return;
            }
            try {
                session.close(new CloseStatus(code, reason));
            } catch (IOException exception) {
                LOG.debug("Could not close a live session: {}", exception.getClass().getSimpleName());
            }
        }
    }
}
