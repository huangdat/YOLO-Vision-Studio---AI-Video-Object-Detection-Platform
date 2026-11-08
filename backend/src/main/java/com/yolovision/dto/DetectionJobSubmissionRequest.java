package com.yolovision.dto;

import com.yolovision.entity.DetectionSourceType;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;
import java.util.List;

/**
 * Internal submission input (no public endpoint until Phase 06). Null confidence,
 * image size, or classes select the engine defaults: 0.25, 960, and COCO vehicle classes.
 */
public record DetectionJobSubmissionRequest(
        @NotBlank @Pattern(regexp = "^[a-z0-9][a-z0-9_-]{0,63}$", message = "must be a registered model key")
        String modelKey,
        @NotNull DetectionSourceType sourceType,
        @NotBlank @Size(max = 2048) String source,
        @DecimalMin("0.0") @DecimalMax("1.0") @Digits(integer = 1, fraction = 3) BigDecimal confidence,
        @Min(32) @Max(4096) Integer imageSize,
        @Size(min = 1, max = 100) List<@NotNull @Min(0) @Max(9999) Integer> classes) {
}
