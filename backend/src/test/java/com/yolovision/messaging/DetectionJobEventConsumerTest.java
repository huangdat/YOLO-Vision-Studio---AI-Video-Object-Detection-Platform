package com.yolovision.messaging;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.yolovision.dto.messaging.DetectionEventMessage;
import com.yolovision.dto.messaging.DetectionEventStatus;
import com.yolovision.exception.UnknownDetectionJobException;
import com.yolovision.service.DetectionJobLifecycleService;
import jakarta.validation.Validation;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.dao.DataAccessResourceFailureException;

class DetectionJobEventConsumerTest {

    private static final String JOB = "3f1d2a4e-8a7b-4c1d-9e2f-0123456789ab";
    private static final String EVENT = "9b2c7d1e-4f3a-4b5c-8d6e-abcdefabcdef";

    private DetectionJobLifecycleService lifecycle;
    private DetectionJobEventConsumer consumer;

    @BeforeEach
    void setUp() {
        lifecycle = mock(DetectionJobLifecycleService.class);
        ObjectMapper mapper = JsonMapper.builder().findAndAddModules().build();
        consumer = new DetectionJobEventConsumer(mapper,
                Validation.buildDefaultValidatorFactory().getValidator(), lifecycle);
    }

    @Test
    void validProgressEventIsDeserialisedAndApplied() {
        when(lifecycle.apply(any())).thenReturn(DetectionJobLifecycleService.Outcome.APPLIED);

        consumer.onEvent(message("""
                {"schemaVersion":1,"eventId":"%s","jobId":"%s","status":"DETECTING","progress":65,
                 "processedFrames":3250,"totalFrames":5000,"message":"Processing video frames",
                 "timestamp":"2026-11-08T00:00:00Z"}""".formatted(EVENT, JOB)));

        ArgumentCaptor<DetectionEventMessage> captor = ArgumentCaptor.forClass(DetectionEventMessage.class);
        verify(lifecycle).apply(captor.capture());
        DetectionEventMessage event = captor.getValue();
        assertThat(event.jobId()).isEqualTo(UUID.fromString(JOB));
        assertThat(event.status()).isEqualTo(DetectionEventStatus.DETECTING);
        assertThat(event.progress()).isEqualTo(65);
        assertThat(event.processedFrames()).isEqualTo(3250);
    }

    @Test
    void pythonStyleOffsetTimestampsAndCompletionPayloadAreAccepted() {
        when(lifecycle.apply(any())).thenReturn(DetectionJobLifecycleService.Outcome.APPLIED);

        consumer.onEvent(message("""
                {"schemaVersion":1,"eventId":"%s","jobId":"%s","status":"COMPLETED","progress":100,
                 "timestamp":"2026-11-08T00:00:00.123456+00:00","modelKey":"yolo26s",
                 "result":{"outputVideoKey":"detections/%s/detected.mp4","resultJsonKey":"detections/%s/result.json",
                 "totalFrames":150,"processingTimeMs":45000,"detectionSummary":{"car":120,"motorcycle":45}}}"""
                .formatted(EVENT, JOB, JOB, JOB)));

        verify(lifecycle).apply(any());
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "not json",
        "{}",
        "null",
        // unknown schema version
        "{\"schemaVersion\":2,\"eventId\":\"" + EVENT + "\",\"jobId\":\"" + JOB + "\",\"status\":\"DETECTING\",\"progress\":5,\"timestamp\":\"2026-11-08T00:00:00Z\"}",
        // backend-owned status
        "{\"schemaVersion\":1,\"eventId\":\"" + EVENT + "\",\"jobId\":\"" + JOB + "\",\"status\":\"QUEUED\",\"progress\":5,\"timestamp\":\"2026-11-08T00:00:00Z\"}",
        // progress out of range
        "{\"schemaVersion\":1,\"eventId\":\"" + EVENT + "\",\"jobId\":\"" + JOB + "\",\"status\":\"DETECTING\",\"progress\":101,\"timestamp\":\"2026-11-08T00:00:00Z\"}",
        // job id is not a UUID
        "{\"schemaVersion\":1,\"eventId\":\"" + EVENT + "\",\"jobId\":\"42\",\"status\":\"DETECTING\",\"progress\":5,\"timestamp\":\"2026-11-08T00:00:00Z\"}",
        // completion without result
        "{\"schemaVersion\":1,\"eventId\":\"" + EVENT + "\",\"jobId\":\"" + JOB + "\",\"status\":\"COMPLETED\",\"progress\":100,\"modelKey\":\"yolo26s\",\"timestamp\":\"2026-11-08T00:00:00Z\"}",
        // failure without error
        "{\"schemaVersion\":1,\"eventId\":\"" + EVENT + "\",\"jobId\":\"" + JOB + "\",\"status\":\"FAILED\",\"progress\":10,\"timestamp\":\"2026-11-08T00:00:00Z\"}",
        // progress event carrying an error
        "{\"schemaVersion\":1,\"eventId\":\"" + EVENT + "\",\"jobId\":\"" + JOB + "\",\"status\":\"DETECTING\",\"progress\":10,\"timestamp\":\"2026-11-08T00:00:00Z\",\"error\":{\"code\":\"X\",\"message\":\"y\"}}",
        // negative statistics
        "{\"schemaVersion\":1,\"eventId\":\"" + EVENT + "\",\"jobId\":\"" + JOB + "\",\"status\":\"COMPLETED\",\"progress\":100,\"modelKey\":\"yolo26s\",\"timestamp\":\"2026-11-08T00:00:00Z\",\"result\":{\"outputVideoKey\":\"a\",\"resultJsonKey\":\"b\",\"totalFrames\":-1,\"processingTimeMs\":1,\"detectionSummary\":{}}}"
    })
    void malformedOrInvalidEventsAreRejectedWithoutRequeueAndNeverApplied(String body) {
        assertThatThrownBy(() -> consumer.onEvent(message(body)))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class);
        verifyNoInteractions(lifecycle);
    }

    @Test
    void unknownJobIsDeadLetteredInsteadOfRetried() {
        when(lifecycle.apply(any())).thenThrow(new UnknownDetectionJobException(UUID.fromString(JOB)));

        assertThatThrownBy(() -> consumer.onEvent(message(progressJson())))
                .isInstanceOf(AmqpRejectAndDontRequeueException.class)
                .hasMessageContaining("unknown job");
    }

    @Test
    void databaseFailuresPropagateUnwrappedSoTheBoundedRetryPolicyApplies() {
        when(lifecycle.apply(any())).thenThrow(new DataAccessResourceFailureException("database down"));

        assertThatThrownBy(() -> consumer.onEvent(message(progressJson())))
                .isInstanceOf(DataAccessResourceFailureException.class);
    }

    private static String progressJson() {
        return "{\"schemaVersion\":1,\"eventId\":\"" + EVENT + "\",\"jobId\":\"" + JOB
                + "\",\"status\":\"DETECTING\",\"progress\":5,\"timestamp\":\"2026-11-08T00:00:00Z\"}";
    }

    private static Message message(String body) {
        return new Message(body.getBytes(StandardCharsets.UTF_8), new MessageProperties());
    }
}
