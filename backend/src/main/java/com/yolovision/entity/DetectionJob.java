package com.yolovision.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.ForeignKey;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/** A detection request and its persisted state; transitions are applied by DetectionJobLifecycleService. */
@Entity
@Table(name = "detection_jobs")
public class DetectionJob {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @NotNull
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "model_id", nullable = false,
            foreignKey = @ForeignKey(name = "fk_detection_jobs_model"))
    private ModelConfig model;

    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "source_type", nullable = false, length = 32)
    private DetectionSourceType sourceType = DetectionSourceType.YOUTUBE_URL;

    @NotBlank
    @Column(name = "video_url", nullable = false, columnDefinition = "text")
    private String videoUrl;

    @NotNull
    @DecimalMin("0.000")
    @DecimalMax("1.000")
    @Digits(integer = 1, fraction = 3)
    @Column(name = "confidence", nullable = false, precision = 4, scale = 3)
    private BigDecimal confidence;

    @NotNull
    @Positive
    @Column(name = "image_size", nullable = false)
    private Integer imageSize;

    @NotNull
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "selected_classes", nullable = false, columnDefinition = "jsonb")
    private List<@NotNull @PositiveOrZero Integer> selectedClasses;

    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private DetectionJobStatus status = DetectionJobStatus.PENDING;

    @Min(0)
    @Max(100)
    @Column(name = "progress", nullable = false)
    private int progress;

    @Column(name = "error_code", length = 64)
    private String errorCode;

    @Column(name = "error_message", columnDefinition = "text")
    private String errorMessage;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "started_at")
    private Instant startedAt;

    @Column(name = "completed_at")
    private Instant completedAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected DetectionJob() {
    }

    public DetectionJob(ModelConfig model, String videoUrl, BigDecimal confidence,
            Integer imageSize, List<Integer> selectedClasses) {
        this.model = model;
        this.videoUrl = videoUrl;
        this.confidence = confidence;
        this.imageSize = imageSize;
        setSelectedClasses(selectedClasses);
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

    public ModelConfig getModel() {
        return model;
    }

    public DetectionSourceType getSourceType() {
        return sourceType;
    }

    public void setSourceType(DetectionSourceType sourceType) {
        this.sourceType = sourceType;
    }

    public String getVideoUrl() {
        return videoUrl;
    }

    public void setVideoUrl(String videoUrl) {
        this.videoUrl = videoUrl;
    }

    public BigDecimal getConfidence() {
        return confidence;
    }

    public void setConfidence(BigDecimal confidence) {
        this.confidence = confidence;
    }

    public Integer getImageSize() {
        return imageSize;
    }

    public void setImageSize(Integer imageSize) {
        this.imageSize = imageSize;
    }

    public List<Integer> getSelectedClasses() {
        return selectedClasses == null ? null : Collections.unmodifiableList(selectedClasses);
    }

    public void setSelectedClasses(List<Integer> selectedClasses) {
        this.selectedClasses = selectedClasses == null ? null : new ArrayList<>(selectedClasses);
    }

    public DetectionJobStatus getStatus() {
        return status;
    }

    public void setStatus(DetectionJobStatus status) {
        this.status = status;
    }

    public int getProgress() {
        return progress;
    }

    public void setProgress(int progress) {
        this.progress = progress;
    }

    public String getErrorCode() {
        return errorCode;
    }

    public void setErrorCode(String errorCode) {
        this.errorCode = errorCode;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public void setErrorMessage(String errorMessage) {
        this.errorMessage = errorMessage;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getStartedAt() {
        return startedAt;
    }

    public void setStartedAt(Instant startedAt) {
        this.startedAt = startedAt;
    }

    public Instant getCompletedAt() {
        return completedAt;
    }

    public void setCompletedAt(Instant completedAt) {
        this.completedAt = completedAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    /** Records worker activity even when no other column changes (lease heartbeat). */
    public void markActivity() {
        updatedAt = Instant.now();
    }
}
