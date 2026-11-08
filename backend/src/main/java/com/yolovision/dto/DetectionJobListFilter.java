package com.yolovision.dto;

import com.yolovision.entity.DetectionJobStatus;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;

/** Query parameters for GET /api/v1/detections; null page/size use 0 and 10. */
public record DetectionJobListFilter(
        @Min(value = 0, message = "must be 0 or greater") Integer page,
        @Min(value = 1, message = "must be between 1 and 100") @Max(value = 100, message = "must be between 1 and 100")
        Integer size,
        DetectionJobStatus status,
        @Pattern(regexp = "^[a-z0-9][a-z0-9_-]{0,63}$", message = "must be a model key such as yolo11n")
        String modelKey) {

    public static final int DEFAULT_SIZE = 10;

    public int pageOrDefault() {
        return page == null ? 0 : page;
    }

    public int sizeOrDefault() {
        return size == null ? DEFAULT_SIZE : size;
    }
}
