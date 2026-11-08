package com.yolovision.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.UUID;

/** Model metadata does not imply that weights are installed or available to workers. */
@Entity
@Table(name = "model_configs", uniqueConstraints =
        @UniqueConstraint(name = "uk_model_configs_model_key", columnNames = "model_key"))
public class ModelConfig {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @NotBlank
    @Size(max = 64)
    @Column(name = "model_key", nullable = false, length = 64, updatable = false)
    private String modelKey;

    @NotBlank
    @Size(max = 32)
    @Column(name = "version", nullable = false, length = 32)
    private String version;

    @NotBlank
    @Size(max = 16)
    @Column(name = "model_size", nullable = false, length = 16)
    private String modelSize;

    @NotBlank
    @Size(max = 32)
    @Column(name = "task_type", nullable = false, length = 32)
    private String taskType;

    @NotBlank
    @Size(max = 255)
    @Column(name = "weights_filename", nullable = false)
    private String weightsFilename;

    @Column(name = "enabled", nullable = false)
    private boolean enabled;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected ModelConfig() {
    }

    public ModelConfig(String modelKey, String version, String modelSize, String taskType, String weightsFilename) {
        this.modelKey = modelKey;
        this.version = version;
        this.modelSize = modelSize;
        this.taskType = taskType;
        this.weightsFilename = weightsFilename;
    }

    @PrePersist
    private void beforeInsert() {
        Instant now = Instant.now();
        createdAt = now;
        updatedAt = now;
    }

    @PreUpdate
    private void beforeUpdate() {
        updatedAt = Instant.now();
    }

    public UUID getId() {
        return id;
    }

    public String getModelKey() {
        return modelKey;
    }

    public String getVersion() {
        return version;
    }

    public void setVersion(String version) {
        this.version = version;
    }

    public String getModelSize() {
        return modelSize;
    }

    public void setModelSize(String modelSize) {
        this.modelSize = modelSize;
    }

    public String getTaskType() {
        return taskType;
    }

    public void setTaskType(String taskType) {
        this.taskType = taskType;
    }

    public String getWeightsFilename() {
        return weightsFilename;
    }

    public void setWeightsFilename(String weightsFilename) {
        this.weightsFilename = weightsFilename;
    }

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
