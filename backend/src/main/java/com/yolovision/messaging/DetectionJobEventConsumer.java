package com.yolovision.messaging;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yolovision.dto.messaging.DetectionEventMessage;
import com.yolovision.dto.messaging.DetectionEventStatus;
import com.yolovision.exception.UnknownDetectionJobException;
import com.yolovision.service.DetectionJobLifecycleService;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validator;
import java.io.IOException;
import java.util.Set;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

/**
 * Applies worker events to PostgreSQL. The message is acknowledged only after the
 * lifecycle transaction committed (AUTO acknowledge mode). Contract violations and
 * unknown jobs are dead-lettered at once; other failures (for example a database
 * outage) are retried a bounded number of times and then dead-lettered.
 */
@Component
public class DetectionJobEventConsumer {

    private static final Logger LOG = LoggerFactory.getLogger(DetectionJobEventConsumer.class);

    private final ObjectMapper objectMapper;
    private final Validator validator;
    private final DetectionJobLifecycleService lifecycle;

    public DetectionJobEventConsumer(ObjectMapper objectMapper, Validator validator,
            DetectionJobLifecycleService lifecycle) {
        this.objectMapper = objectMapper;
        this.validator = validator;
        this.lifecycle = lifecycle;
    }

    @RabbitListener(id = "detectionJobEvents", queues = "${app.messaging.event-queue}")
    public void onEvent(Message message) {
        DetectionEventMessage event = parse(message.getBody());
        try {
            DetectionJobLifecycleService.Outcome outcome = lifecycle.apply(event);
            if (outcome == DetectionJobLifecycleService.Outcome.APPLIED) {
                LOG.debug("Event {} for job {} applied: {} {}%", event.eventId(), event.jobId(),
                        event.status(), event.progress());
            } else if (outcome != DetectionJobLifecycleService.Outcome.HEARTBEAT) {
                LOG.info("Event {} for job {} ({}) was not applied: {}", event.eventId(), event.jobId(),
                        event.status(), outcome);
            }
        } catch (UnknownDetectionJobException exception) {
            throw new AmqpRejectAndDontRequeueException(
                    "Event " + event.eventId() + " references unknown job " + event.jobId());
        }
    }

    DetectionEventMessage parse(byte[] body) {
        DetectionEventMessage event;
        try {
            event = objectMapper.readValue(body, DetectionEventMessage.class);
        } catch (IOException exception) {
            throw new AmqpRejectAndDontRequeueException("Malformed detection event JSON", exception);
        }
        if (event == null) {
            throw new AmqpRejectAndDontRequeueException("Empty detection event");
        }
        Set<ConstraintViolation<DetectionEventMessage>> violations = validator.validate(event);
        if (!violations.isEmpty()) {
            throw new AmqpRejectAndDontRequeueException("Invalid detection event: " + violations.stream()
                    .map(violation -> violation.getPropertyPath() + " " + violation.getMessage())
                    .sorted().collect(Collectors.joining(", ")));
        }
        String problem = contractProblem(event);
        if (problem != null) {
            throw new AmqpRejectAndDontRequeueException("Invalid detection event: " + problem);
        }
        return event;
    }

    private static String contractProblem(DetectionEventMessage event) {
        if (event.schemaVersion() != 1) {
            return "unsupported schemaVersion " + event.schemaVersion();
        }
        boolean completed = event.status() == DetectionEventStatus.COMPLETED;
        boolean failed = event.status() == DetectionEventStatus.FAILED;
        if (completed != (event.result() != null)) {
            return "result is required for and only allowed on COMPLETED";
        }
        if (completed && (event.modelKey() == null || event.progress() != 100)) {
            return "COMPLETED requires modelKey and progress 100";
        }
        if (failed != (event.error() != null)) {
            return "error is required for and only allowed on FAILED";
        }
        return null;
    }
}
