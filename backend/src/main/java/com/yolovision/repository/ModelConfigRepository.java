package com.yolovision.repository;

import com.yolovision.entity.ModelConfig;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ModelConfigRepository extends JpaRepository<ModelConfig, UUID> {

    Optional<ModelConfig> findByModelKey(String modelKey);

    List<ModelConfig> findByEnabledTrueOrderByModelKeyAsc();

    boolean existsByModelKey(String modelKey);
}
