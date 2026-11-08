package com.yolovision.entity;

import static org.assertj.core.api.Assertions.assertThat;

import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

/** Fast application validation; PostgreSQL checks are exercised separately through JDBC. */
class PersistenceValidationTest {

    private static ValidatorFactory factory;
    private static Validator validator;

    @BeforeAll
    static void createValidator() {
        factory = Validation.buildDefaultValidatorFactory();
        validator = factory.getValidator();
    }

    @AfterAll
    static void closeValidator() {
        factory.close();
    }

    @ParameterizedTest
    @ValueSource(strings = {"-0.001", "1.001", "0.1234"})
    void confidenceRejectsOutOfRangeOrExcessPrecisionValues(String value) {
        DetectionJob job = newJob();
        job.setConfidence(new BigDecimal(value));

        assertThat(validator.validate(job)).extracting(violation -> violation.getPropertyPath().toString())
                .contains("confidence");
    }

    @ParameterizedTest
    @ValueSource(ints = {-1, 101})
    void progressMustStayWithinItsInclusiveBounds(int progress) {
        DetectionJob job = newJob();
        job.setProgress(progress);

        assertThat(validator.validate(job)).extracting(violation -> violation.getPropertyPath().toString())
                .contains("progress");
    }

    @ParameterizedTest
    @ValueSource(ints = {0, -1})
    void imageSizeMustBePositive(int imageSize) {
        DetectionJob job = newJob();
        job.setImageSize(imageSize);

        assertThat(validator.validate(job)).extracting(violation -> violation.getPropertyPath().toString())
                .contains("imageSize");
    }

    @Test
    void selectedClassesRejectNegativeClassIdentifiers() {
        DetectionJob job = newJob();
        job.setSelectedClasses(List.of(0, -1, 79));

        assertThat(validator.validate(job))
                .anyMatch(violation -> violation.getPropertyPath().toString().startsWith("selectedClasses"));
    }

    @Test
    void detectionStatisticsRejectNegativeCounts() {
        DetectionResult result = new DetectionResult(newJob(), "results/output.mp4", Map.of("car", -1L));

        assertThat(validator.validate(result))
                .anyMatch(violation -> violation.getPropertyPath().toString().startsWith("detectionSummary"));
    }

    private DetectionJob newJob() {
        ModelConfig model = new ModelConfig("validation-model", "TEST_VERSION", "s", "DETECT", "test-model.pt");
        return new DetectionJob(model, "https://example.com/video", new BigDecimal("0.450"),
                640, List.of(0, 2, 79));
    }
}
