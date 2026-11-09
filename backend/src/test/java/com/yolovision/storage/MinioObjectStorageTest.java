package com.yolovision.storage;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.yolovision.config.ObjectStorageProperties;
import com.yolovision.exception.StorageUnavailableException;
import java.net.ServerSocket;
import java.time.Duration;
import org.junit.jupiter.api.Test;

class MinioObjectStorageTest {

    private static ObjectStorageProperties properties(String endpoint, String secret) {
        return new ObjectStorageProperties(endpoint, "yolovision", secret, "videos", null,
                Duration.ofSeconds(1), Duration.ofSeconds(1));
    }

    @Test
    void aMissingSecretMeansUnavailableNotACrash() {
        MinioObjectStorage storage = new MinioObjectStorage(properties("http://127.0.0.1:9000", ""));

        assertThatThrownBy(() -> storage.stat("detections/x/detected.mp4"))
                .isInstanceOf(StorageUnavailableException.class)
                .hasMessage("Artifact storage is temporarily unavailable.");
    }

    @Test
    void anUnreachableEndpointIsUnavailableWithAClientSafeMessage() throws Exception {
        int closedPort;
        try (ServerSocket socket = new ServerSocket(0)) {
            closedPort = socket.getLocalPort();
        }
        MinioObjectStorage storage = new MinioObjectStorage(properties("http://127.0.0.1:" + closedPort, "secret-value"));

        assertThatThrownBy(() -> storage.stat("detections/x/detected.mp4"))
                .isInstanceOf(StorageUnavailableException.class)
                .hasMessage("Artifact storage is temporarily unavailable.")
                .hasMessageNotContaining("127.0.0.1");
        assertThatThrownBy(() -> storage.open("detections/x/detected.mp4", 0, 10))
                .isInstanceOf(StorageUnavailableException.class);
    }

    @Test
    void propertiesNeverPrintTheSecret() {
        assertThat(properties("http://minio:9000", "super-secret").toString()).doesNotContain("super-secret");
    }
}
