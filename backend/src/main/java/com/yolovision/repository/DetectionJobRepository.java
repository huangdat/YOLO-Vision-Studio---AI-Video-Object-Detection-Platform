package com.yolovision.repository;

import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DetectionJobRepository extends JpaRepository<DetectionJob, UUID> {

    Page<DetectionJob> findByStatus(DetectionJobStatus status, Pageable pageable);

    Page<DetectionJob> findAllByOrderByCreatedAtDescIdDesc(Pageable pageable);

    Page<DetectionJob> findByStatusOrderByCreatedAtDescIdDesc(DetectionJobStatus status, Pageable pageable);

    Page<DetectionJob> findByModel_Id(UUID modelId, Pageable pageable);
}
