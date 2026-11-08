package com.yolovision.service;

import com.yolovision.dto.ModelCatalogFilter;
import com.yolovision.dto.ModelCatalogResponse;
import com.yolovision.dto.ModelConfigResponse;
import com.yolovision.dto.ModelVersionsResponse;
import com.yolovision.entity.ModelConfig;
import com.yolovision.exception.ModelNotFoundException;
import com.yolovision.repository.ModelConfigRepository;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Read-only access to registered model metadata. The database is authoritative for
 * catalog membership and administrative enablement; it says nothing about whether
 * a worker has cached or verified the weights.
 */
@Service
@Transactional(readOnly = true)
public class ModelCatalogService {

    private static final Pattern MODEL_KEY = Pattern.compile("^[a-z0-9][a-z0-9_-]{0,63}$");
    private static final Pattern GENERATION = Pattern.compile("(\\d+)");
    private static final List<String> SIZE_ORDER = List.of("n", "s", "m", "l", "x");

    /** Release generation (YOLOv8 = 8 before YOLO11 = 11), not lexical order, then n to x. */
    static final Comparator<String> VERSION_ORDER = Comparator
            .comparingInt(ModelCatalogService::generation)
            .thenComparing(Comparator.naturalOrder());
    static final Comparator<ModelConfig> CATALOG_ORDER = Comparator
            .comparing(ModelConfig::getVersion, VERSION_ORDER)
            .thenComparingInt(model -> sizeRank(model.getModelSize()))
            .thenComparing(ModelConfig::getModelSize)
            .thenComparing(ModelConfig::getModelKey);

    private final ModelConfigRepository models;

    public ModelCatalogService(ModelConfigRepository models) {
        this.models = models;
    }

    public ModelCatalogResponse listModels(ModelCatalogFilter filter) {
        List<Specification<ModelConfig>> criteria = new ArrayList<>();
        if (filter.version() != null) {
            criteria.add(ModelConfigRepository.hasVersion(filter.version()));
        }
        if (filter.size() != null) {
            criteria.add(ModelConfigRepository.hasModelSize(filter.size()));
        }
        if (filter.enabled() != null) {
            criteria.add(ModelConfigRepository.isEnabled(filter.enabled()));
        }
        return ModelCatalogResponse.of(models.findAll(Specification.allOf(criteria)).stream()
                .sorted(CATALOG_ORDER)
                .map(ModelConfigResponse::from)
                .toList());
    }

    public ModelConfigResponse getModel(String modelKey) {
        if (modelKey == null || !MODEL_KEY.matcher(modelKey).matches()) {
            throw new ModelNotFoundException();
        }
        return models.findByModelKey(modelKey)
                .map(ModelConfigResponse::from)
                .orElseThrow(ModelNotFoundException::new);
    }

    public ModelVersionsResponse listVersions() {
        return new ModelVersionsResponse(models.findDistinctVersions().stream().sorted(VERSION_ORDER).toList());
    }

    private static int generation(String version) {
        Matcher matcher = GENERATION.matcher(version);
        if (!matcher.find()) {
            return Integer.MAX_VALUE;
        }
        try {
            return Integer.parseInt(matcher.group(1));
        } catch (NumberFormatException exception) {
            return Integer.MAX_VALUE;
        }
    }

    private static int sizeRank(String size) {
        int rank = SIZE_ORDER.indexOf(size);
        return rank < 0 ? SIZE_ORDER.size() : rank;
    }
}
