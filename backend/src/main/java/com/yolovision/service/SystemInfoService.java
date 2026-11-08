package com.yolovision.service;

import com.yolovision.config.ApplicationProperties;
import com.yolovision.dto.SystemInfoResponse;
import org.springframework.stereotype.Service;

@Service
public class SystemInfoService {

    private final ApplicationProperties properties;

    public SystemInfoService(ApplicationProperties properties) {
        this.properties = properties;
    }

    public SystemInfoResponse getSystemInfo() {
        return new SystemInfoResponse(properties.name(), "backend", properties.version(), "UP");
    }
}
