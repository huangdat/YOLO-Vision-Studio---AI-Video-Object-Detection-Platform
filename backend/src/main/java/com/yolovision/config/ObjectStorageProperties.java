package com.yolovision.config;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * Read-only access to the private MinIO bucket that holds worker artifacts. The values are the
 * same MINIO_* variables the worker uses; the secret is never logged or returned by any API.
 */
@Validated
@ConfigurationProperties(prefix = "app.storage")
public record ObjectStorageProperties(
        @NotBlank @Pattern(regexp = "^https?://[^/?#@\\s]+/?$") String endpoint,
        @NotBlank String accessKey,
        /** Optional at startup; artifact requests answer 503 until it is configured. */
        String secretKey,
        @NotBlank @Pattern(regexp = "^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$") String bucket,
        String region,
        @NotNull Duration connectTimeout,
        @NotNull Duration readTimeout) {

    public boolean hasSecretKey() {
        return secretKey != null && !secretKey.isBlank();
    }

    @Override
    public String toString() {
        return "ObjectStorageProperties[endpoint=" + endpoint + ", bucket=" + bucket + ", secretKey=****]";
    }
}
