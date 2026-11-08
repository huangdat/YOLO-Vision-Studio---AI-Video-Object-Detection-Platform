package com.yolovision.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * Detection messaging topology and reliability settings. The topology values must
 * match the Python worker's settings (same RABBITMQ_* environment variables).
 */
@Validated
@ConfigurationProperties(prefix = "app.messaging")
public record MessagingProperties(
        @NotBlank String commandExchange,
        @NotBlank String commandQueue,
        @NotBlank String commandRoutingKey,
        @NotBlank String eventExchange,
        @NotBlank String eventQueue,
        @NotBlank String eventRoutingKey,
        @NotBlank String deadLetterExchange,
        @NotBlank String deadLetterQueue,
        @NotBlank String deadLetterRoutingKey,
        /** Quorum-queue x-delivery-limit: broker-enforced bound on redeliveries. */
        @Min(1) @Max(100) int deliveryLimit,
        @Valid @NotNull Outbox outbox,
        @Valid @NotNull Jobs jobs) {

    public record Outbox(
            boolean enabled,
            @NotNull Duration pollInterval,
            @Min(1) @Max(500) int batchSize,
            @Min(1) @Max(100) int maxAttempts,
            @NotNull Duration initialBackoff,
            @NotNull Duration maxBackoff,
            @NotNull Duration confirmTimeout) {
    }

    public record Jobs(
            boolean leaseMonitorEnabled,
            @NotNull Duration leaseCheckInterval,
            /** Active stages without any worker event for this long are failed. */
            @NotNull Duration processingTimeout,
            /** QUEUED jobs that no worker picked up within this period are failed. */
            @NotNull Duration queueTimeout) {
    }
}
