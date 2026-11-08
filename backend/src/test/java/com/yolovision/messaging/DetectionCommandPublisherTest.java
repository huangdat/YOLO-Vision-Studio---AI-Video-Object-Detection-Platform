package com.yolovision.messaging;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.yolovision.config.MessagingProperties;
import com.yolovision.entity.DetectionJobOutboxMessage;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.AmqpConnectException;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.ReturnedMessage;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.test.util.ReflectionTestUtils;

class DetectionCommandPublisherTest {

    private RabbitTemplate template;
    private DetectionCommandPublisher publisher;
    private DetectionJobOutboxMessage outboxMessage;
    private final AtomicReference<Message> sent = new AtomicReference<>();

    static MessagingProperties properties(Duration confirmTimeout) {
        return new MessagingProperties("cmd.x", "cmd.q", "detection.execute", "evt.x", "evt.q", "detection.status",
                "dl.x", "dl.q", "dead", 5,
                new MessagingProperties.Outbox(true, Duration.ofSeconds(1), 20, 3, Duration.ofSeconds(2),
                        Duration.ofMinutes(5), confirmTimeout),
                new MessagingProperties.Jobs(false, Duration.ofMinutes(1), Duration.ofMinutes(30), Duration.ofDays(1)));
    }

    @BeforeEach
    void setUp() {
        template = mock(RabbitTemplate.class);
        ObjectMapper mapper = JsonMapper.builder().findAndAddModules().build();
        publisher = new DetectionCommandPublisher(template, properties(Duration.ofMillis(200)), mapper);
        outboxMessage = new DetectionJobOutboxMessage(UUID.randomUUID(), UUID.randomUUID(), "detection.execute.v1",
                mapper.createObjectNode().put("schemaVersion", 1).put("modelKey", "yolo11n"));
        ReflectionTestUtils.invokeMethod(outboxMessage, "beforeInsert");
    }

    @Test
    void confirmedCommandIsPersistentJsonWithStableIdentifiers() throws Exception {
        broker(correlation -> correlation.getFuture().complete(new CorrelationData.Confirm(true, null)));

        publisher.publish(outboxMessage);

        Message message = sent.get();
        assertThat(message.getMessageProperties().getDeliveryMode()).isEqualTo(MessageDeliveryMode.PERSISTENT);
        assertThat(message.getMessageProperties().getContentType()).isEqualTo("application/json");
        assertThat(message.getMessageProperties().getMessageId()).isEqualTo(outboxMessage.getId().toString());
        assertThat(message.getMessageProperties().getCorrelationId()).isEqualTo(outboxMessage.getJobId().toString());
        assertThat(message.getMessageProperties().getType()).isEqualTo("detection.execute.v1");
        assertThat(new String(message.getBody())).isEqualTo("{\"schemaVersion\":1,\"modelKey\":\"yolo11n\"}");
    }

    @Test
    void negativeAcknowledgementIsAFailure() {
        broker(correlation -> correlation.getFuture().complete(new CorrelationData.Confirm(false, "disk alarm")));

        assertThatThrownBy(() -> publisher.publish(outboxMessage))
                .isInstanceOf(CommandPublicationException.class).hasMessageContaining("disk alarm");
    }

    @Test
    void unroutableCommandIsAFailureEvenWhenTheBrokerAcknowledgesIt() {
        broker(correlation -> {
            correlation.setReturned(new ReturnedMessage(sent.get(), 312, "NO_ROUTE", "cmd.x", "detection.execute"));
            correlation.getFuture().complete(new CorrelationData.Confirm(true, null));
        });

        assertThatThrownBy(() -> publisher.publish(outboxMessage))
                .isInstanceOf(CommandPublicationException.class).hasMessageContaining("unroutable");
    }

    @Test
    void missingConfirmTimesOut() {
        broker(correlation -> { });

        assertThatThrownBy(() -> publisher.publish(outboxMessage))
                .isInstanceOf(CommandPublicationException.class).hasMessageContaining("confirm");
    }

    @Test
    void brokerConnectionFailureIsAFailure() {
        doThrow(new AmqpConnectException(new java.net.ConnectException("refused")))
                .when(template).send(eq("cmd.x"), eq("detection.execute"), any(Message.class), any(CorrelationData.class));

        assertThatThrownBy(() -> publisher.publish(outboxMessage))
                .isInstanceOf(CommandPublicationException.class).hasMessageContaining("Broker unavailable");
    }

    private void broker(Consumer<CorrelationData> behaviour) {
        doAnswer(invocation -> {
            sent.set(invocation.getArgument(2));
            behaviour.accept(invocation.getArgument(3));
            return null;
        }).when(template).send(eq("cmd.x"), eq("detection.execute"), any(Message.class), any(CorrelationData.class));
    }
}
