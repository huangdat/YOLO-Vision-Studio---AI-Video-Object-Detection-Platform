package com.yolovision.repository;

import com.yolovision.entity.DetectionResult;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DetectionResultRepository extends JpaRepository<DetectionResult, UUID> {

    Optional<DetectionResult> findByJob_Id(UUID jobId);

    boolean existsByJob_Id(UUID jobId);
}
