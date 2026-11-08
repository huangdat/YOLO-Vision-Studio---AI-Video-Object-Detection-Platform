package com.yolovision.dto;

import jakarta.validation.constraints.Pattern;

/**
 * Optional catalog filters bound from query parameters. A well-formed value that
 * matches no registered model yields an empty list rather than an error.
 */
public record ModelCatalogFilter(
        @Pattern(regexp = "^YOLO(v?\\d{1,3})$",
                message = "must be a YOLO version label such as YOLOv8, YOLO11, YOLO12, or YOLO26")
        String version,
        @Pattern(regexp = "^[nsmlx]$", message = "must be one of n, s, m, l, or x")
        String size,
        Boolean enabled) {
}
