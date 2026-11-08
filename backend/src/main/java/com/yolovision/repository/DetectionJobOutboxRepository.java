package com.yolovision.repository;

import com.yolovision.entity.DetectionJobOutboxMessage;
import com.yolovision.entity.DetectionJobOutboxMessage.Status;
import jakarta.persistence.LockModeType;
import jakarta.persistence.QueryHint;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.QueryHints;
import org.springframework.data.repository.query.Param;

public interface DetectionJobOutboxRepository extends JpaRepository<DetectionJobOutboxMessage, UUID> {

    /**
     * Due messages, locked for this transaction. Rows locked by another publisher
     * instance are skipped (lock timeout -2 = SKIP LOCKED), so instances never
     * publish the same row concurrently.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @QueryHints(@QueryHint(name = "jakarta.persistence.lock.timeout", value = "-2"))
    @Query("""
            SELECT m FROM DetectionJobOutboxMessage m
            WHERE m.status = :status AND m.nextAttemptAt <= :now
            ORDER BY m.nextAttemptAt, m.createdAt
            """)
    List<DetectionJobOutboxMessage> lockDue(@Param("status") Status status, @Param("now") Instant now, Pageable page);

    Optional<DetectionJobOutboxMessage> findByJobIdAndMessageType(UUID jobId, String messageType);

    long countByStatus(Status status);
}
