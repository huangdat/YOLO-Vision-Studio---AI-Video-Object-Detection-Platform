package com.yolovision.repository;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import com.yolovision.entity.DetectionResult;
import com.yolovision.entity.ModelConfig;
import jakarta.persistence.EntityManager;
import java.math.BigDecimal;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.hibernate.Hibernate;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;

/** The same repository contract is exercised on H2 and on PostgreSQL. */
@Transactional
abstract class AbstractRepositoryPersistenceTests {

    @Autowired
    protected ModelConfigRepository models;

    @Autowired
    protected DetectionJobRepository jobs;

    @Autowired
    protected DetectionResultRepository results;

    @Autowired
    protected EntityManager entityManager;

    @Autowired
    protected JdbcTemplate jdbc;

    @Test
    void modelRoundTripsItsBusinessKeyMetadataAndDisabledDefault() {
        ModelConfig model = models.saveAndFlush(newModel());
        UUID id = model.getId();
        entityManager.clear();

        ModelConfig reloaded = models.findByModelKey(model.getModelKey()).orElseThrow();

        assertThat(id).isNotNull();
        assertThat(reloaded.getId()).isEqualTo(id);
        assertThat(reloaded.getVersion()).isEqualTo("TEST_VERSION");
        assertThat(reloaded.getModelSize()).isEqualTo("s");
        assertThat(reloaded.getTaskType()).isEqualTo("DETECT");
        assertThat(reloaded.getWeightsFilename()).isEqualTo("test-model.pt");
        assertThat(reloaded.isEnabled()).isFalse();
        assertThat(reloaded.getCreatedAt()).isNotNull();
        assertThat(reloaded.getUpdatedAt()).isEqualTo(reloaded.getCreatedAt());
        assertThat(models.existsByModelKey(model.getModelKey())).isTrue();
        assertThat(models.existsByModelKey("missing-" + UUID.randomUUID())).isFalse();
    }

    @Test
    void enabledModelQueryExcludesUnavailableMetadataAndSortsByKey() {
        ModelConfig disabled = models.saveAndFlush(newModel());
        ModelConfig enabledB = newModel("test-b-" + UUID.randomUUID());
        enabledB.setEnabled(true);
        models.saveAndFlush(enabledB);
        ModelConfig enabledA = newModel("test-a-" + UUID.randomUUID());
        enabledA.setEnabled(true);
        models.saveAndFlush(enabledA);
        entityManager.clear();

        List<ModelConfig> available = models.findByEnabledTrueOrderByModelKeyAsc();

        assertThat(available).extracting(ModelConfig::getId)
                .containsSubsequence(enabledA.getId(), enabledB.getId())
                .doesNotContain(disabled.getId());
        assertThat(available).allMatch(ModelConfig::isEnabled);
        assertThat(available).extracting(ModelConfig::getModelKey).isSorted();
    }

    @Test
    void duplicateModelBusinessKeysAreRejected() {
        ModelConfig first = models.saveAndFlush(newModel());

        assertThatThrownBy(() -> models.saveAndFlush(newModel(first.getModelKey())))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void jobRoundTripsConfigurationDefaultsAndLazyModelRelationship() {
        ModelConfig model = models.saveAndFlush(newModel());
        DetectionJob job = jobs.saveAndFlush(newJob(model));
        UUID jobId = job.getId();
        entityManager.clear();

        DetectionJob reloaded = jobs.findById(jobId).orElseThrow();

        assertThat(reloaded.getId()).isNotNull();
        assertThat(reloaded.getVideoUrl()).isEqualTo("https://example.com/video");
        assertThat(reloaded.getConfidence()).isEqualByComparingTo("0.450");
        assertThat(reloaded.getImageSize()).isEqualTo(640);
        // Includes non-vehicle classes: the persistence contract is general-purpose.
        assertThat(reloaded.getSelectedClasses()).containsExactly(0, 1, 2, 5, 79);
        assertThat(reloaded.getStatus()).isEqualTo(DetectionJobStatus.PENDING);
        assertThat(reloaded.getProgress()).isZero();
        assertThat(reloaded.getErrorMessage()).isNull();
        assertThat(reloaded.getStartedAt()).isNull();
        assertThat(reloaded.getCompletedAt()).isNull();
        assertThat(reloaded.getCreatedAt()).isNotNull();
        assertThat(reloaded.getUpdatedAt()).isEqualTo(reloaded.getCreatedAt());
        assertThat(Hibernate.isInitialized(reloaded.getModel())).isFalse();
        assertThat(reloaded.getModel().getId()).isEqualTo(model.getId());
        assertThat(reloaded.getModel().getModelKey()).isEqualTo(model.getModelKey());
    }

    @Test
    void statusAndProcessingMetadataRoundTripWithoutAProcessingStateMachine() {
        ModelConfig model = models.saveAndFlush(newModel());
        DetectionJob job = newJob(model);
        Instant started = Instant.parse("2026-01-01T10:00:00Z");
        Instant completed = Instant.parse("2026-01-01T10:02:00Z");
        job.setStatus(DetectionJobStatus.FAILED);
        job.setProgress(42);
        job.setErrorMessage("A worker-reported failure");
        job.setStartedAt(started);
        job.setCompletedAt(completed);
        jobs.saveAndFlush(job);
        entityManager.clear();

        DetectionJob reloaded = jobs.findById(job.getId()).orElseThrow();

        assertThat(reloaded.getStatus()).isEqualTo(DetectionJobStatus.FAILED);
        assertThat(reloaded.getProgress()).isEqualTo(42);
        assertThat(reloaded.getErrorMessage()).isEqualTo("A worker-reported failure");
        assertThat(reloaded.getStartedAt()).isEqualTo(started);
        assertThat(reloaded.getCompletedAt()).isEqualTo(completed);
    }

    @Test
    void jobQueriesFilterByStatusAndModelAndPageInCreationOrder() {
        ModelConfig firstModel = models.saveAndFlush(newModel());
        ModelConfig secondModel = models.saveAndFlush(newModel());
        DetectionJob earliest = jobs.saveAndFlush(newJob(firstModel));
        DetectionJob latest = newJob(firstModel);
        latest.setStatus(DetectionJobStatus.QUEUED);
        jobs.saveAndFlush(latest);
        DetectionJob middle = newJob(secondModel);
        middle.setStatus(DetectionJobStatus.QUEUED);
        jobs.saveAndFlush(middle);
        setCreatedAt(earliest, "2026-01-01T00:00:00Z");
        setCreatedAt(middle, "2026-01-02T00:00:00Z");
        setCreatedAt(latest, "2026-01-03T00:00:00Z");
        entityManager.clear();

        Page<DetectionJob> firstPage = jobs.findAllByOrderByCreatedAtDescIdDesc(PageRequest.of(0, 2));
        Page<DetectionJob> secondPage = jobs.findAllByOrderByCreatedAtDescIdDesc(PageRequest.of(1, 2));
        Page<DetectionJob> queued = jobs.findByStatusOrderByCreatedAtDescIdDesc(
                DetectionJobStatus.QUEUED, PageRequest.of(0, 1));

        assertThat(firstPage.getTotalElements()).isEqualTo(3);
        assertThat(firstPage.getContent()).extracting(DetectionJob::getId)
                .containsExactly(latest.getId(), middle.getId());
        assertThat(secondPage.getContent()).extracting(DetectionJob::getId)
                .containsExactly(earliest.getId());
        assertThat(queued.getTotalElements()).isEqualTo(2);
        assertThat(queued.getContent()).extracting(DetectionJob::getId).containsExactly(latest.getId());
        assertThat(jobs.findByStatus(DetectionJobStatus.PENDING, PageRequest.of(0, 10)).getContent())
                .extracting(DetectionJob::getId).containsExactly(earliest.getId());
        Page<DetectionJob> byModel = jobs.findByModel_Id(firstModel.getId(),
                PageRequest.of(0, 10, Sort.by(Sort.Direction.DESC, "createdAt", "id")));
        assertThat(byModel.getContent()).extracting(DetectionJob::getId)
                .containsExactly(latest.getId(), earliest.getId());
    }

    @Test
    void updatesRefreshTimestampsAndPreserveCreationTime() {
        ModelConfig model = models.saveAndFlush(newModel());
        DetectionJob job = jobs.saveAndFlush(newJob(model));
        Instant oldUpdate = Instant.parse("2000-01-01T00:00:00Z");
        jdbc.update("UPDATE model_configs SET updated_at = ? WHERE id = ?", utc(oldUpdate), model.getId());
        jdbc.update("UPDATE detection_jobs SET updated_at = ? WHERE id = ?", utc(oldUpdate), job.getId());
        entityManager.clear();
        ModelConfig loadedModel = models.findById(model.getId()).orElseThrow();
        DetectionJob loadedJob = jobs.findById(job.getId()).orElseThrow();
        Instant modelCreated = loadedModel.getCreatedAt();
        Instant jobCreated = loadedJob.getCreatedAt();

        loadedModel.setEnabled(true);
        loadedJob.setProgress(12);
        entityManager.flush();
        entityManager.clear();

        ModelConfig updatedModel = models.findById(model.getId()).orElseThrow();
        DetectionJob updatedJob = jobs.findById(job.getId()).orElseThrow();
        assertThat(updatedModel.getUpdatedAt()).isAfter(oldUpdate);
        assertThat(updatedJob.getUpdatedAt()).isAfter(oldUpdate);
        assertThat(updatedModel.getCreatedAt()).isEqualTo(modelCreated);
        assertThat(updatedJob.getCreatedAt()).isEqualTo(jobCreated);
    }

    @Test
    void resultRoundTripsStorageReferencesStatisticsAndItsLazyJob() {
        DetectionJob job = persistedJob();
        assertThat(results.existsByJob_Id(job.getId())).isFalse();
        Map<String, Long> summary = Map.of("car", 120L, "motorcycle", 45L, "person", 7L);
        DetectionResult result = new DetectionResult(job, "results/annotated.mp4", summary);
        result.setInputVideoKey("inputs/source.mp4");
        result.setTotalFrames(900);
        result.setProcessingTimeMs(12_345L);
        results.saveAndFlush(result);
        entityManager.clear();

        DetectionResult reloaded = results.findByJob_Id(job.getId()).orElseThrow();

        assertThat(reloaded.getId()).isNotNull();
        assertThat(reloaded.getInputVideoKey()).isEqualTo("inputs/source.mp4");
        assertThat(reloaded.getOutputVideoKey()).isEqualTo("results/annotated.mp4");
        assertThat(reloaded.getTotalFrames()).isEqualTo(900);
        assertThat(reloaded.getProcessingTimeMs()).isEqualTo(12_345L);
        assertThat(reloaded.getDetectionSummary()).isEqualTo(summary);
        assertThat(reloaded.getCreatedAt()).isNotNull();
        assertThat(results.existsByJob_Id(job.getId())).isTrue();
        assertThat(Hibernate.isInitialized(reloaded.getJob())).isFalse();
        assertThat(reloaded.getJob().getId()).isEqualTo(job.getId());
    }

    @Test
    void duplicateResultsForTheSameJobAreRejected() {
        DetectionJob job = persistedJob();
        results.saveAndFlush(new DetectionResult(job, "results/first.mp4", Map.of()));

        assertThatThrownBy(() -> results.saveAndFlush(
                new DetectionResult(job, "results/second.mp4", Map.of())))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void jobsCannotReferenceMissingModels() {
        ModelConfig missing = entityManager.getReference(ModelConfig.class, UUID.randomUUID());

        assertThatThrownBy(() -> jobs.saveAndFlush(newJob(missing)))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void resultsCannotReferenceMissingJobs() {
        DetectionJob missing = entityManager.getReference(DetectionJob.class, UUID.randomUUID());

        assertThatThrownBy(() -> results.saveAndFlush(
                new DetectionResult(missing, "results/orphan.mp4", Map.of())))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void deletingAReferencedModelIsRejected() {
        DetectionJob job = persistedJob();
        UUID modelId = job.getModel().getId();
        // Exercise the database FK instead of Hibernate's managed-object graph checks.
        entityManager.clear();

        assertThatThrownBy(() -> {
            models.deleteById(modelId);
            models.flush();
        }).isInstanceOf(DataIntegrityViolationException.class);
    }

    protected DetectionJob persistedJob() {
        return jobs.saveAndFlush(newJob(models.saveAndFlush(newModel())));
    }

    protected ModelConfig newModel() {
        return newModel("test-" + UUID.randomUUID());
    }

    protected ModelConfig newModel(String key) {
        return new ModelConfig(key, "TEST_VERSION", "s", "DETECT", "test-model.pt");
    }

    protected DetectionJob newJob(ModelConfig model) {
        return new DetectionJob(model, "https://example.com/video", new BigDecimal("0.450"),
                640, List.of(0, 1, 2, 5, 79));
    }

    private void setCreatedAt(DetectionJob job, String timestamp) {
        jdbc.update("UPDATE detection_jobs SET created_at = ? WHERE id = ?",
                utc(Instant.parse(timestamp)), job.getId());
    }

    private OffsetDateTime utc(Instant instant) {
        return instant.atOffset(ZoneOffset.UTC);
    }
}
