package com.yolovision.config;

import java.util.Map;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Declarables;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.ExchangeBuilder;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConversionException;
import org.springframework.boot.autoconfigure.amqp.RabbitProperties;
import org.springframework.boot.autoconfigure.amqp.RabbitRetryTemplateCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.retry.policy.SimpleRetryPolicy;

/**
 * Detection topology. Connections use Spring Boot's environment-backed spring.rabbitmq
 * settings; publisher confirms, returns, and listener retry are configured in application.yaml.
 *
 * <p>Both queues are durable quorum queues with a broker-enforced delivery limit and a
 * dead-letter exchange, so a poison message can never be redelivered forever. The Python
 * worker declares the same entities with identical arguments.
 */
@Configuration(proxyBeanMethods = false)
public class RabbitConfiguration {

    @Bean
    public Jackson2JsonMessageConverter rabbitMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }

    @Bean
    public Declarables detectionTopology(MessagingProperties messaging) {
        DirectExchange commands = durableExchange(messaging.commandExchange());
        DirectExchange events = durableExchange(messaging.eventExchange());
        DirectExchange deadLetters = durableExchange(messaging.deadLetterExchange());
        Queue jobs = workQueue(messaging.commandQueue(), messaging);
        Queue eventQueue = workQueue(messaging.eventQueue(), messaging);
        Queue deadLetterQueue = QueueBuilder.durable(messaging.deadLetterQueue()).quorum().build();
        Binding jobBinding = BindingBuilder.bind(jobs).to(commands).with(messaging.commandRoutingKey());
        Binding eventBinding = BindingBuilder.bind(eventQueue).to(events).with(messaging.eventRoutingKey());
        Binding deadLetterBinding = BindingBuilder.bind(deadLetterQueue).to(deadLetters)
                .with(messaging.deadLetterRoutingKey());
        return new Declarables(commands, events, deadLetters, jobs, eventQueue, deadLetterQueue,
                jobBinding, eventBinding, deadLetterBinding);
    }

    /**
     * Listener retry covers transient failures (for example a database outage). Contract
     * violations are rejected immediately and dead-lettered instead of being retried.
     */
    @Bean
    public RabbitRetryTemplateCustomizer detectionListenerRetryClassifier(RabbitProperties rabbit) {
        return (target, template) -> {
            if (target == RabbitRetryTemplateCustomizer.Target.LISTENER) {
                int attempts = rabbit.getListener().getSimple().getRetry().getMaxAttempts();
                template.setRetryPolicy(new SimpleRetryPolicy(attempts, Map.of(
                        AmqpRejectAndDontRequeueException.class, false,
                        MessageConversionException.class, false), true, true));
            }
        };
    }

    static Queue workQueue(String name, MessagingProperties messaging) {
        return QueueBuilder.durable(name)
                .quorum()
                .deliveryLimit(messaging.deliveryLimit())
                .deadLetterExchange(messaging.deadLetterExchange())
                .deadLetterRoutingKey(messaging.deadLetterRoutingKey())
                .build();
    }

    private static DirectExchange durableExchange(String name) {
        return ExchangeBuilder.directExchange(name).durable(true).build();
    }
}
