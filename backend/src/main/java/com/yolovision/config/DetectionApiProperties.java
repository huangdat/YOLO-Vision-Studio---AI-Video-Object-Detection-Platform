package com.yolovision.config;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "app.detection-api")
public record DetectionApiProperties(
        /** Upper bound for a detection request body; larger requests receive 413. */
        @Min(1024) @Max(1048576) int maxRequestBytes) {
}
