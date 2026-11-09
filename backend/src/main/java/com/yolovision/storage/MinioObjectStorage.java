package com.yolovision.storage;

import com.yolovision.config.ObjectStorageProperties;
import com.yolovision.exception.StorageObjectNotFoundException;
import com.yolovision.exception.StorageUnavailableException;
import io.minio.GetObjectArgs;
import io.minio.MinioClient;
import io.minio.StatObjectArgs;
import io.minio.StatObjectResponse;
import io.minio.errors.ErrorResponseException;
import java.io.InputStream;
import java.util.Set;
import okhttp3.OkHttpClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/**
 * MinIO implementation. The client is created on first use, so the application starts without
 * storage and artifact requests answer 503 until it is reachable. Only stat and ranged GET are
 * used: nothing here writes, lists, deletes, or changes bucket policy.
 */
@Component
public class MinioObjectStorage implements ObjectStorage {

    private static final Logger LOG = LoggerFactory.getLogger(MinioObjectStorage.class);
    private static final Set<String> MISSING = Set.of("NoSuchKey", "NoSuchBucket", "NoSuchObject", "NotFound");

    private final ObjectStorageProperties properties;
    private volatile MinioClient client;

    public MinioObjectStorage(ObjectStorageProperties properties) {
        this.properties = properties;
    }

    /** One startup line for operators: where artifacts are read from (never the secret). */
    @EventListener(ApplicationReadyEvent.class)
    public void logConfiguration() {
        LOG.info("Artifact storage: endpoint={}, bucket={}, credentials {}", properties.endpoint(),
                properties.bucket(), properties.hasSecretKey() ? "configured" : "MISSING (artifact requests answer 503)");
    }

    @Override
    public StoredObject stat(String key) {
        try {
            StatObjectResponse stat = client().statObject(
                    StatObjectArgs.builder().bucket(properties.bucket()).object(key).build());
            return new StoredObject(key, stat.size(), stat.contentType(), stat.etag());
        } catch (Exception exception) {
            throw translate(exception);
        }
    }

    @Override
    public InputStream open(String key, long offset, long length) {
        try {
            return client().getObject(GetObjectArgs.builder().bucket(properties.bucket()).object(key)
                    .offset(offset).length(length).build());
        } catch (Exception exception) {
            throw translate(exception);
        }
    }

    private RuntimeException translate(Exception exception) {
        if (exception instanceof StorageUnavailableException unavailable) {
            return unavailable;
        }
        if (exception instanceof ErrorResponseException response
                && MISSING.contains(response.errorResponse().code())) {
            return new StorageObjectNotFoundException();
        }
        // Log the type only: storage messages can include the endpoint and request details.
        LOG.warn("Object storage request failed: {}", exception.getClass().getSimpleName());
        return new StorageUnavailableException(exception);
    }

    private MinioClient client() {
        MinioClient current = client;
        if (current == null) {
            synchronized (this) {
                if (client == null) {
                    if (!properties.hasSecretKey()) {
                        LOG.warn("MINIO_SECRET_KEY is not configured; artifact requests are unavailable");
                        throw new StorageUnavailableException();
                    }
                    OkHttpClient http = new OkHttpClient.Builder()
                            .connectTimeout(properties.connectTimeout())
                            .readTimeout(properties.readTimeout())
                            .writeTimeout(properties.readTimeout())
                            .build();
                    MinioClient.Builder builder = MinioClient.builder()
                            .endpoint(properties.endpoint())
                            .credentials(properties.accessKey(), properties.secretKey())
                            .httpClient(http);
                    if (properties.region() != null && !properties.region().isBlank()) {
                        builder.region(properties.region());
                    }
                    client = builder.build();
                }
                current = client;
            }
        }
        return current;
    }
}
