package com.yolovision.config;

import com.yolovision.controller.LiveDetectionWebSocketHandler;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

/**
 * Registers the Live Detection WebSocket. The handshake accepts same-origin requests (the UI
 * through the Vite or nginx proxy, which preserve the Host header) and the explicitly
 * configured {@code CORS_ALLOWED_ORIGINS}; never a wildcard. Origin checks are not
 * authentication: like the rest of the API this is for localhost or trusted networks only.
 */
@Configuration(proxyBeanMethods = false)
@EnableWebSocket
public class LiveWebSocketConfiguration implements WebSocketConfigurer {

    public static final String PATH = "/api/v1/live/ws";

    private final LiveDetectionWebSocketHandler handler;
    private final ApplicationProperties application;

    public LiveWebSocketConfiguration(LiveDetectionWebSocketHandler handler, ApplicationProperties application) {
        this.handler = handler;
        this.application = application;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(handler, PATH)
                .setAllowedOrigins(application.corsAllowedOrigins().toArray(String[]::new));
    }
}
