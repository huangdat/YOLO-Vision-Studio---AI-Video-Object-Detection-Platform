package com.yolovision.controller;

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.everyItem;
import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.is;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

/** The catalog API served from real Flyway seed data and real PostgreSQL queries. */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("postgres-test")
@Testcontainers
class ModelApiPostgreSQLIT {

    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:17-bookworm");

    @DynamicPropertySource
    static void isolatedPostgresqlDatasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
    }

    @Autowired
    private MockMvc mockMvc;

    @Test
    void listsTheSeededCatalogInReleaseAndSizeOrder() throws Exception {
        mockMvc.perform(get("/api/v1/models"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(20))
                .andExpect(jsonPath("$.models[0].modelKey").value("yolov8n"))
                .andExpect(jsonPath("$.models[4].modelKey").value("yolov8x"))
                .andExpect(jsonPath("$.models[5].modelKey").value("yolo11n"))
                .andExpect(jsonPath("$.models[19].modelKey").value("yolo26x"))
                .andExpect(jsonPath("$.models[*].enabled", everyItem(is(false))));
    }

    @Test
    void filtersRunAgainstPostgresql() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("version", "YOLO26"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.models[*].modelKey")
                        .value(contains("yolo26n", "yolo26s", "yolo26m", "yolo26l", "yolo26x")));
        mockMvc.perform(get("/api/v1/models").param("size", "n"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.models[*].modelKey")
                        .value(contains("yolov8n", "yolo11n", "yolo12n", "yolo26n")));
        mockMvc.perform(get("/api/v1/models").param("enabled", "true"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0));
        mockMvc.perform(get("/api/v1/models").param("enabled", "false").param("version", "YOLOv8").param("size", "m"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.models", hasSize(1)))
                .andExpect(jsonPath("$.models[0].weightsFilename").value("yolov8m.pt"));
    }

    @Test
    void detailsAndVersionsComeFromTheDatabase() throws Exception {
        mockMvc.perform(get("/api/v1/models/yolo26s"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.version").value("YOLO26"))
                .andExpect(jsonPath("$.enabled").value(false));
        mockMvc.perform(get("/api/v1/models/yolov5s")).andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/models/versions"))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"versions":["YOLOv8","YOLO11","YOLO12","YOLO26"]}
                        """, org.springframework.test.json.JsonCompareMode.STRICT));
    }
}
