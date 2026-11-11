package com.yolovision.config;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import java.time.Duration;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * Live Detection (webcam) gateway limits. Defaults are deliberately conservative for CPU
 * inference on a developer machine; they are starting points, not performance guarantees.
 */
@Validated
@ConfigurationProperties(prefix = "app.live")
public record LiveDetectionProperties(
        /** Internal ai-live-worker base URL; never exposed to browsers. */
        @NotNull @Pattern(regexp = "^https?://[^/?#@\\s]+/?$") String workerUrl,
        @Min(1) @Max(16) int maxSessions,
        @Min(1) @Max(30) int maxFps,
        @Min(1024) @Max(8388608) int maxFrameBytes,
        @NotEmpty List<@Min(32) @Max(1280) Integer> imageSizes,
        @NotEmpty List<@Pattern(regexp = "^[nslmx]$") String> modelSizes,
        @NotNull Duration inferenceTimeout,
        @NotNull Duration loadTimeout,
        @NotNull Duration idleTimeout,
        @NotNull Duration maxSessionDuration,
        @NotNull Duration sendTimeLimit) {

    /** Minimum spacing between accepted frames (with 15 % tolerance for timer jitter). */
    public long minFrameIntervalNanos() {
        return (long) (1_000_000_000L / maxFps * 0.85);
    }
}
