package com.yolovision.config;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/** Server-Sent Events for job progress: bounded connections, one shared poller. */
@Validated
@ConfigurationProperties(prefix = "app.detection-stream")
public record DetectionStreamProperties(
        @NotNull Duration timeout,
        @NotNull Duration pollInterval,
        @NotNull Duration heartbeatInterval,
        @Min(1) @Max(10000) int maxConnections,
        @NotNull Duration reconnectDelay) {
}
