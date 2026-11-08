package com.yolovision.dto;

import java.util.List;

public record ModelVersionsResponse(List<String> versions) {

    public ModelVersionsResponse {
        versions = List.copyOf(versions);
    }
}
