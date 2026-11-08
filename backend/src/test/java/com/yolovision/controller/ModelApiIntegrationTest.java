package com.yolovision.controller;

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.hasKey;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.yolovision.entity.ModelConfig;
import com.yolovision.repository.ModelConfigRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

/** H2 only exercises the web and JPA contract; PostgreSQL ITs verify the Flyway catalog itself. */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Transactional
class ModelApiIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ModelConfigRepository models;

    @BeforeEach
    void registerModelsOutOfOrder() {
        models.deleteAll();
        save("yolo26s", "YOLO26", "s", true);
        save("yolo11n", "YOLO11", "n", false);
        save("yolov8s", "YOLOv8", "s", false);
        save("yolo26n", "YOLO26", "n", false);
        save("yolov8n", "YOLOv8", "n", false);
        save("yolo12x", "YOLO12", "x", false);
        models.flush();
    }

    @Test
    void listReturnsActualRecordsSortedByReleaseGenerationThenSize() throws Exception {
        mockMvc.perform(get("/api/v1/models"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.total").value(6))
                .andExpect(jsonPath("$.models[*].modelKey")
                        .value(contains("yolov8n", "yolov8s", "yolo11n", "yolo12x", "yolo26n", "yolo26s")));
    }

    @Test
    void modelEntriesUseTheResponseDtoAndExposeNoFilesystemPaths() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("version", "YOLO26").param("size", "s"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(1))
                .andExpect(jsonPath("$.models[0].id").isNotEmpty())
                .andExpect(jsonPath("$.models[0].modelKey").value("yolo26s"))
                .andExpect(jsonPath("$.models[0].version").value("YOLO26"))
                .andExpect(jsonPath("$.models[0].modelSize").value("s"))
                .andExpect(jsonPath("$.models[0].taskType").value("DETECT"))
                .andExpect(jsonPath("$.models[0].weightsFilename").value("yolo26s.pt"))
                .andExpect(jsonPath("$.models[0].enabled").value(true))
                .andExpect(jsonPath("$.models[0].createdAt").isNotEmpty())
                .andExpect(jsonPath("$.models[0]", not(hasKey("path"))))
                .andExpect(jsonPath("$.models[0]", not(hasKey("weightsPath"))));
    }

    @Test
    void filtersByVersion() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("version", "YOLO26"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(2))
                .andExpect(jsonPath("$.models[*].modelKey").value(contains("yolo26n", "yolo26s")));
    }

    @Test
    void filtersBySize() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("size", "n"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(3))
                .andExpect(jsonPath("$.models[*].modelKey").value(contains("yolov8n", "yolo11n", "yolo26n")));
    }

    @Test
    void filtersByAdministrativeEnablement() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("enabled", "true"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(1))
                .andExpect(jsonPath("$.models[0].modelKey").value("yolo26s"));
        mockMvc.perform(get("/api/v1/models").param("enabled", "false"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(5));
    }

    @Test
    void combinesFilters() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("version", "YOLOv8").param("size", "s").param("enabled", "false"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(1))
                .andExpect(jsonPath("$.models[0].modelKey").value("yolov8s"));
    }

    @Test
    void wellFormedFiltersWithoutMatchesReturnAnEmptyList() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("version", "YOLOv5"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0))
                .andExpect(jsonPath("$.models").isEmpty());
        mockMvc.perform(get("/api/v1/models").param("version", "YOLO12").param("size", "n"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0));
    }

    @Test
    void emptyCatalogReturnsAnEmptyListAndNoVersions() throws Exception {
        models.deleteAll();
        models.flush();

        mockMvc.perform(get("/api/v1/models"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0));
        mockMvc.perform(get("/api/v1/models/versions"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.versions").isEmpty());
    }

    @Test
    void invalidVersionFilterIsABadRequestWithFieldErrors() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("version", "yolo26' OR 1=1"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.detail").value("Request validation failed."))
                .andExpect(jsonPath("$.errors.version").isNotEmpty());
    }

    @Test
    void invalidSizeFilterIsABadRequest() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("size", "xl"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errors.size").value("must be one of n, s, m, l, or x"));
    }

    @Test
    void invalidEnabledFilterIsABadRequest() throws Exception {
        mockMvc.perform(get("/api/v1/models").param("enabled", "sometimes"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.errors.enabled").isNotEmpty());
    }

    @Test
    void detailsReturnOneModel() throws Exception {
        mockMvc.perform(get("/api/v1/models/yolov8n"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.modelKey").value("yolov8n"))
                .andExpect(jsonPath("$.version").value("YOLOv8"))
                .andExpect(jsonPath("$.weightsFilename").value("yolov8n.pt"))
                .andExpect(jsonPath("$.enabled").value(false));
    }

    @Test
    void unknownModelIsNotFoundWithProblemDetails() throws Exception {
        mockMvc.perform(get("/api/v1/models/yolov5s"))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(404))
                .andExpect(jsonPath("$.title").value("Model not found"))
                .andExpect(jsonPath("$.detail").value("The requested model is not registered."));
    }

    @Test
    void malformedModelKeysAreNotFoundAndNotEchoed() throws Exception {
        for (String key : new String[] {"YOLO26S", "yolo26s.pt", "%2E%2E", "a".repeat(65)}) {
            mockMvc.perform(get("/api/v1/models/" + key))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.detail").value("The requested model is not registered."));
        }
    }

    @Test
    void versionsAreDistinctAndOrderedByReleaseAndNotTreatedAsAModelKey() throws Exception {
        mockMvc.perform(get("/api/v1/models/versions"))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"versions":["YOLOv8","YOLO11","YOLO12","YOLO26"]}
                        """, org.springframework.test.json.JsonCompareMode.STRICT));
    }

    @Test
    void catalogIsReadOnly() throws Exception {
        mockMvc.perform(post("/api/v1/models").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isMethodNotAllowed());
        mockMvc.perform(delete("/api/v1/models/yolo26s"))
                .andExpect(status().isMethodNotAllowed());
        mockMvc.perform(post("/api/v1/models/yolo26s/prepare"))
                .andExpect(status().isNotFound());
    }

    @Test
    void allowedFrontendOriginCanReadTheCatalog() throws Exception {
        mockMvc.perform(get("/api/v1/models").header(HttpHeaders.ORIGIN, "http://localhost:5173"))
                .andExpect(status().isOk())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.header()
                        .string(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, "http://localhost:5173"));
    }

    private void save(String key, String version, String size, boolean enabled) {
        ModelConfig model = new ModelConfig(key, version, size, "DETECT", key + ".pt");
        model.setEnabled(enabled);
        models.save(model);
    }
}
