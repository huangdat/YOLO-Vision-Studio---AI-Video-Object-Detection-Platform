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
import org.springframework.data.jpa.domain.Specification;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface DetectionJobRepository extends JpaRepository<DetectionJob, UUID>,
        JpaSpecificationExecutor<DetectionJob> {

    Page<DetectionJob> findByStatus(DetectionJobStatus status, Pageable pageable);

    Page<DetectionJob> findAllByOrderByCreatedAtDescIdDesc(Pageable pageable);

    Page<DetectionJob> findByStatusOrderByCreatedAtDescIdDesc(DetectionJobStatus status, Pageable pageable);

    Page<DetectionJob> findByModel_Id(UUID modelId, Pageable pageable);

    /** Serialises event handling per job, so duplicate events cannot race each other. */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT j FROM DetectionJob j WHERE j.id = :id")
    Optional<DetectionJob> findByIdForUpdate(@Param("id") UUID id);

    /** One job with its model in a single query (no lazy loading after the transaction). */
    @EntityGraph(attributePaths = "model")
    Optional<DetectionJob> findWithModelById(UUID id);

    /** Filtered history page; the model is fetched with each job to avoid N+1 queries. */
    @Override
    @EntityGraph(attributePaths = "model")
    Page<DetectionJob> findAll(Specification<DetectionJob> specification, Pageable pageable);

    /** Current progress of several jobs in one query, for the SSE poller. */
    @Query("SELECT j.id AS id, j.status AS status, j.progress AS progress, j.errorCode AS errorCode, "
            + "j.errorMessage AS errorMessage, j.updatedAt AS updatedAt FROM DetectionJob j WHERE j.id IN :ids")
    List<DetectionJobProgressView> findProgressByIdIn(@Param("ids") Collection<UUID> ids);

    static Specification<DetectionJob> hasStatus(DetectionJobStatus status) {
        return (root, query, builder) -> builder.equal(root.get("status"), status);
    }

    static Specification<DetectionJob> hasModelKey(String modelKey) {
        return (root, query, builder) -> builder.equal(root.join("model").get("modelKey"), modelKey);
    }

    /** Ids of non-terminal jobs whose last recorded activity is older than the cutoff. */
    @Query("SELECT j.id FROM DetectionJob j WHERE j.status IN :statuses AND j.updatedAt < :cutoff")
    List<UUID> findStaleJobIds(@Param("statuses") Collection<DetectionJobStatus> statuses,
            @Param("cutoff") Instant cutoff, Pageable page);
}
