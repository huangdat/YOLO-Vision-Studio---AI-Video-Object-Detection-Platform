package com.yolovision.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.yolovision.controller.ModelController;
import com.yolovision.dto.ModelCatalogFilter;
import com.yolovision.dto.ModelConfigResponse;
import com.yolovision.entity.ModelConfig;
import com.yolovision.exception.GlobalExceptionHandler;
import com.yolovision.exception.ModelNotFoundException;
import com.yolovision.repository.ModelConfigRepository;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class ModelCatalogServiceTest {

    private ModelConfigRepository repository;
    private ModelCatalogService service;

    @BeforeEach
    void setUp() {
        repository = mock(ModelConfigRepository.class);
        service = new ModelCatalogService(repository);
    }

    @Test
    @SuppressWarnings("unchecked")
    void listSortsYolov8BeforeYolo11AndNanoBeforeExtraLarge() {
        when(repository.findAll(any(Specification.class))).thenReturn(List.of(
                model("yolo26x", "YOLO26", "x"), model("yolo11n", "YOLO11", "n"),
                model("yolov8x", "YOLOv8", "x"), model("yolov8n", "YOLOv8", "n"),
                model("yolo26n", "YOLO26", "n"), model("yolo12m", "YOLO12", "m"),
                model("yolo26m", "YOLO26", "m"), model("yolo26l", "YOLO26", "l"), model("yolo26s", "YOLO26", "s")));

        List<String> keys = service.listModels(new ModelCatalogFilter(null, null, null)).models().stream()
                .map(ModelConfigResponse::modelKey).toList();

        assertThat(keys).containsExactly(
                "yolov8n", "yolov8x", "yolo11n", "yolo12m", "yolo26n", "yolo26s", "yolo26m", "yolo26l", "yolo26x");
    }

    @Test
    void versionsAreOrderedByGenerationWithUnrecognizedLabelsLast() {
        when(repository.findDistinctVersions()).thenReturn(List.of("YOLO26", "CUSTOM", "YOLO11", "YOLOv8", "YOLO12"));

        assertThat(service.listVersions().versions())
                .containsExactly("YOLOv8", "YOLO11", "YOLO12", "YOLO26", "CUSTOM");
    }

    @Test
    void malformedKeysAreRejectedWithoutQueryingTheDatabase() {
        for (String key : new String[] {null, "", "../yolo26s", "YOLO26S", "yolo26s.pt", "a".repeat(65)}) {
            assertThatThrownBy(() -> service.getModel(key)).isInstanceOf(ModelNotFoundException.class);
        }
        verifyNoInteractions(repository);
    }

    @Test
    void unknownKeysAreNotFound() {
        when(repository.findByModelKey("yolov5s")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.getModel("yolov5s")).isInstanceOf(ModelNotFoundException.class);
    }

    @Test
    @SuppressWarnings("unchecked")
    void databaseFailuresBecomeServiceUnavailableProblemDetailsWithoutInternals() throws Exception {
        when(repository.findAll(any(Specification.class)))
                .thenThrow(new DataAccessResourceFailureException("Connection to db-internal:5432 refused"));
        when(repository.findByModelKey(any()))
                .thenThrow(new DataAccessResourceFailureException("Connection to db-internal:5432 refused"));
        MockMvc mockMvc = MockMvcBuilders.standaloneSetup(new ModelController(service))
                .setControllerAdvice(new GlobalExceptionHandler()).build();

        for (String path : new String[] {"/api/v1/models", "/api/v1/models/yolo26s"}) {
            mockMvc.perform(get(path))
                    .andExpect(status().isServiceUnavailable())
                    .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                    .andExpect(jsonPath("$.status").value(503))
                    .andExpect(jsonPath("$.detail").value("The data store is temporarily unavailable."));
        }
    }

    private static ModelConfig model(String key, String version, String size) {
        return new ModelConfig(key, version, size, "DETECT", key + ".pt");
    }
}
