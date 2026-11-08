package com.yolovision.controller;

import com.yolovision.dto.ModelCatalogFilter;
import com.yolovision.dto.ModelCatalogResponse;
import com.yolovision.dto.ModelConfigResponse;
import com.yolovision.dto.ModelVersionsResponse;
import com.yolovision.service.ModelCatalogService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Read-only model catalog. Preparation and downloads are worker-side operator actions only. */
@RestController
@RequestMapping("/api/v1/models")
public class ModelController {

    private final ModelCatalogService modelCatalogService;

    public ModelController(ModelCatalogService modelCatalogService) {
        this.modelCatalogService = modelCatalogService;
    }

    @GetMapping
    public ModelCatalogResponse listModels(@Valid @ModelAttribute ModelCatalogFilter filter) {
        return modelCatalogService.listModels(filter);
    }

    // A literal path segment takes precedence over the {modelKey} pattern below.
    @GetMapping("/versions")
    public ModelVersionsResponse listVersions() {
        return modelCatalogService.listVersions();
    }

    @GetMapping("/{modelKey}")
    public ModelConfigResponse getModel(@PathVariable String modelKey) {
        return modelCatalogService.getModel(modelKey);
    }
}
