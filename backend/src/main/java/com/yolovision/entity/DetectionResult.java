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
import jakarta.persistence.OneToOne;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import java.time.Instant;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/** Result metadata; summary values are detection statistics, not unique object counts. */
@Entity
@Table(name = "detection_results")
public class DetectionResult {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @NotNull
    @OneToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "job_id", nullable = false, unique = true,
            foreignKey = @ForeignKey(name = "fk_detection_results_job"))
    private DetectionJob job;

    @Column(name = "input_video_key", columnDefinition = "text")
    private String inputVideoKey;

    @NotBlank
    @Column(name = "output_video_key", nullable = false, columnDefinition = "text")
    private String outputVideoKey;

    @Column(name = "result_json_key", columnDefinition = "text")
    private String resultJsonKey;

    @PositiveOrZero
    @Column(name = "total_frames")
    private Integer totalFrames;

    @PositiveOrZero
    @Column(name = "processing_time_ms")
    private Long processingTimeMs;

    @NotNull
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "detection_summary", nullable = false, columnDefinition = "jsonb")
    private Map<@NotBlank String, @NotNull @PositiveOrZero Long> detectionSummary;

    /** Tracking totals; null for detection-only results (including every legacy result). */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "tracking_summary", columnDefinition = "jsonb")
    private TrackingSummary trackingSummary;

    /** Precision and runtime the worker actually used; null for results stored before it reported them. */
    @Enumerated(EnumType.STRING)
    @Column(name = "effective_precision", length = 8)
    private InferencePrecision effectivePrecision;

    @Enumerated(EnumType.STRING)
    @Column(name = "inference_runtime", length = 16)
    private InferenceRuntime inferenceRuntime;

    /** Device the worker actually ran the model on ("cpu", "cuda:0"); null when not reported. */
    @Column(name = "inference_device", length = 16)
    private String inferenceDevice;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    protected DetectionResult() {
    }

    public DetectionResult(DetectionJob job, String outputVideoKey, Map<String, Long> detectionSummary) {
        this.job = job;
        this.outputVideoKey = outputVideoKey;
        setDetectionSummary(detectionSummary);
    }

    @PrePersist
    private void beforeInsert() {
        createdAt = Instant.now();
    }

    public UUID getId() {
        return id;
    }

    public TrackingSummary getTrackingSummary() {
        return trackingSummary;
    }

    public void setTrackingSummary(TrackingSummary trackingSummary) {
        this.trackingSummary = trackingSummary;
    }

    public InferencePrecision getEffectivePrecision() {
        return effectivePrecision;
    }

    public void setEffectivePrecision(InferencePrecision effectivePrecision) {
        this.effectivePrecision = effectivePrecision;
    }

    public InferenceRuntime getInferenceRuntime() {
        return inferenceRuntime;
    }

    public void setInferenceRuntime(InferenceRuntime inferenceRuntime) {
        this.inferenceRuntime = inferenceRuntime;
    }

    public String getInferenceDevice() {
        return inferenceDevice;
    }

    public void setInferenceDevice(String inferenceDevice) {
        this.inferenceDevice = inferenceDevice;
    }

    public DetectionJob getJob() {
        return job;
    }

    public String getInputVideoKey() {
        return inputVideoKey;
    }

    public void setInputVideoKey(String inputVideoKey) {
        this.inputVideoKey = inputVideoKey;
    }

    public String getOutputVideoKey() {
        return outputVideoKey;
    }

    public void setOutputVideoKey(String outputVideoKey) {
        this.outputVideoKey = outputVideoKey;
    }

    public String getResultJsonKey() {
        return resultJsonKey;
    }

    public void setResultJsonKey(String resultJsonKey) {
        this.resultJsonKey = resultJsonKey;
    }

    public Integer getTotalFrames() {
        return totalFrames;
    }

    public void setTotalFrames(Integer totalFrames) {
        this.totalFrames = totalFrames;
    }

    public Long getProcessingTimeMs() {
        return processingTimeMs;
    }

    public void setProcessingTimeMs(Long processingTimeMs) {
        this.processingTimeMs = processingTimeMs;
    }

    public Map<String, Long> getDetectionSummary() {
        return detectionSummary == null ? null : Collections.unmodifiableMap(detectionSummary);
    }

    public void setDetectionSummary(Map<String, Long> detectionSummary) {
        this.detectionSummary = detectionSummary == null ? null : new LinkedHashMap<>(detectionSummary);
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
