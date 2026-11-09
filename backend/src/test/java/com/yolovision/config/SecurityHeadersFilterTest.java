package com.yolovision.config;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.UUID;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class SecurityHeadersFilterTest {

    @Autowired
    private MockMvc mockMvc;

    @ParameterizedTest
    @ValueSource(strings = {"/api/v1/system/info", "/api/v1/models", "/actuator/health", "/api/v1/detections/not-a-uuid"})
    void everyResponseCarriesBaselineSecurityHeaders(String path) throws Exception {
        mockMvc.perform(get(path))
                .andExpect(header().stringValues("X-Content-Type-Options", "nosniff"))
                .andExpect(header().string("X-Frame-Options", "DENY"))
                .andExpect(header().string("Referrer-Policy", "no-referrer"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"/result.json", "/video"})
    void errorResponsesFromArtifactsAlsoCarryThem(String artifact) throws Exception {
        mockMvc.perform(get("/api/v1/detections/" + UUID.randomUUID() + artifact))
                .andExpect(status().isNotFound())
                .andExpect(header().stringValues("X-Content-Type-Options", "nosniff"));
    }
}
