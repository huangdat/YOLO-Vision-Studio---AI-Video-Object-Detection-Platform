package com.yolovision.repository;

import com.yolovision.entity.ModelConfig;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Query;

public interface ModelConfigRepository extends JpaRepository<ModelConfig, UUID>, JpaSpecificationExecutor<ModelConfig> {

    Optional<ModelConfig> findByModelKey(String modelKey);

    List<ModelConfig> findByEnabledTrueOrderByModelKeyAsc();

    boolean existsByModelKey(String modelKey);

    @Query("SELECT DISTINCT m.version FROM ModelConfig m")
    List<String> findDistinctVersions();

    static Specification<ModelConfig> hasVersion(String version) {
        return (root, query, builder) -> builder.equal(root.get("version"), version);
    }

    static Specification<ModelConfig> hasModelSize(String modelSize) {
        return (root, query, builder) -> builder.equal(root.get("modelSize"), modelSize);
    }

    static Specification<ModelConfig> isEnabled(boolean enabled) {
        return (root, query, builder) -> builder.equal(root.get("enabled"), enabled);
    }
}
