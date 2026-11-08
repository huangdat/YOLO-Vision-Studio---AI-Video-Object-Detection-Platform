package com.yolovision.repository;

import com.yolovision.entity.DetectionJob;
import com.yolovision.entity.DetectionJobStatus;
import jakarta.persistence.LockModeType;
import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface DetectionJobRepository extends JpaRepository<DetectionJob, UUID> {

    Page<DetectionJob> findByStatus(DetectionJobStatus status, Pageable pageable);

    Page<DetectionJob> findAllByOrderByCreatedAtDescIdDesc(Pageable pageable);

    Page<DetectionJob> findByStatusOrderByCreatedAtDescIdDesc(DetectionJobStatus status, Pageable pageable);

    Page<DetectionJob> findByModel_Id(UUID modelId, Pageable pageable);

    /** Serialises event handling per job, so duplicate events cannot race each other. */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT j FROM DetectionJob j WHERE j.id = :id")
    Optional<DetectionJob> findByIdForUpdate(@Param("id") UUID id);

    /** Ids of non-terminal jobs whose last recorded activity is older than the cutoff. */
    @Query("SELECT j.id FROM DetectionJob j WHERE j.status IN :statuses AND j.updatedAt < :cutoff")
    List<UUID> findStaleJobIds(@Param("statuses") Collection<DetectionJobStatus> statuses,
            @Param("cutoff") Instant cutoff, Pageable page);
}
