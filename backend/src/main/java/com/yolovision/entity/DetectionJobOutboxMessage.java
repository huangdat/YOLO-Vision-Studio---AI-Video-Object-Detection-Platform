package com.yolovision.entity;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/**
 * A broker message written in the same transaction as its job. The id is reused as
 * the AMQP message id so consumers can recognise republished duplicates.
 */
@Entity
@Table(name = "detection_job_outbox")
public class DetectionJobOutboxMessage {

    public enum Status { PENDING, PUBLISHED, FAILED }

    @Id
    private UUID id;

    @Column(name = "job_id", nullable = false, updatable = false)
    private UUID jobId;

    @Column(name = "message_type", nullable = false, length = 64, updatable = false)
    private String messageType;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "payload", nullable = false, columnDefinition = "jsonb", updatable = false)
    private JsonNode payload;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 16)
    private Status status = Status.PENDING;

    @Column(name = "attempts", nullable = false)
    private int attempts;

    @Column(name = "next_attempt_at", nullable = false)
    private Instant nextAttemptAt;

    @Column(name = "last_error", columnDefinition = "text")
    private String lastError;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "published_at")
    private Instant publishedAt;

    protected DetectionJobOutboxMessage() {
    }

    public DetectionJobOutboxMessage(UUID id, UUID jobId, String messageType, JsonNode payload) {
        this.id = id;
        this.jobId = jobId;
        this.messageType = messageType;
        this.payload = payload;
    }

    @PrePersist
    private void beforeInsert() {
        createdAt = Instant.now();
        if (nextAttemptAt == null) {
            nextAttemptAt = createdAt;
        }
    }

    public void markPublished(Instant when) {
        status = Status.PUBLISHED;
        publishedAt = when;
        lastError = null;
    }

    /** Records a failed attempt; returns true when the retry budget is exhausted. */
    public boolean recordFailure(String error, Instant retryAt, int maxAttempts) {
        attempts++;
        lastError = error;
        nextAttemptAt = retryAt;
        if (attempts >= maxAttempts) {
            status = Status.FAILED;
            return true;
        }
        return false;
    }

    public UUID getId() {
        return id;
    }

    public UUID getJobId() {
        return jobId;
    }

    public String getMessageType() {
        return messageType;
    }

    public JsonNode getPayload() {
        return payload;
    }

    public Status getStatus() {
        return status;
    }

    public int getAttempts() {
        return attempts;
    }

    public Instant getNextAttemptAt() {
        return nextAttemptAt;
    }

    public String getLastError() {
        return lastError;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getPublishedAt() {
        return publishedAt;
    }
}
