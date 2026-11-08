package com.yolovision.messaging;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yolovision.config.MessagingProperties;
import com.yolovision.dto.messaging.DetectionCommandMessage;
import com.yolovision.entity.DetectionJobOutboxMessage;
import java.util.Date;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

/**
 * Sends one outbox command and waits for the broker's publisher confirm. A command
 * counts as published only when it was routed to a queue (mandatory, no return) and
 * acknowledged by the broker (persisted by the durable quorum queue).
 */
@Component
public class DetectionCommandPublisher {

    private final RabbitTemplate rabbitTemplate;
    private final MessagingProperties messaging;
    private final ObjectMapper objectMapper;

    public DetectionCommandPublisher(RabbitTemplate rabbitTemplate, MessagingProperties messaging,
            ObjectMapper objectMapper) {
        this.rabbitTemplate = rabbitTemplate;
        this.messaging = messaging;
        this.objectMapper = objectMapper;
    }

    public void publish(DetectionJobOutboxMessage outboxMessage) throws CommandPublicationException {
        Message message = toAmqpMessage(outboxMessage);
        CorrelationData correlation = new CorrelationData(outboxMessage.getId().toString());
        try {
            rabbitTemplate.send(messaging.commandExchange(), messaging.commandRoutingKey(), message, correlation);
            CorrelationData.Confirm confirm = correlation.getFuture()
                    .get(messaging.outbox().confirmTimeout().toMillis(), TimeUnit.MILLISECONDS);
            if (correlation.getReturned() != null) {
                throw new CommandPublicationException("Command was unroutable (reply code "
                        + correlation.getReturned().getReplyCode() + "); the job queue may be missing");
            }
            if (!confirm.isAck()) {
                throw new CommandPublicationException("Broker rejected the command: " + confirm.getReason());
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new CommandPublicationException("Interrupted while awaiting the publisher confirm", exception);
        } catch (TimeoutException exception) {
            throw new CommandPublicationException("No publisher confirm within the configured timeout", exception);
        } catch (ExecutionException | AmqpException exception) {
            throw new CommandPublicationException("Broker unavailable: " + exception.getClass().getSimpleName(),
                    exception);
        }
    }

    Message toAmqpMessage(DetectionJobOutboxMessage outboxMessage) throws CommandPublicationException {
        byte[] body;
        try {
            body = objectMapper.writeValueAsBytes(outboxMessage.getPayload());
        } catch (JsonProcessingException exception) {
            throw new CommandPublicationException("Outbox payload could not be serialised", exception);
        }
        return MessageBuilder.withBody(body)
                .setContentType(MessageProperties.CONTENT_TYPE_JSON)
                .setContentEncoding("utf-8")
                .setMessageId(outboxMessage.getId().toString())
                .setCorrelationId(outboxMessage.getJobId().toString())
                .setType(outboxMessage.getMessageType())
                .setDeliveryMode(MessageDeliveryMode.PERSISTENT)
                .setTimestamp(Date.from(outboxMessage.getCreatedAt()))
                .setHeader("schemaVersion", DetectionCommandMessage.SCHEMA_VERSION)
                .build();
    }
}
