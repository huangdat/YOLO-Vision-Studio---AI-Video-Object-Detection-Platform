package com.yolovision.config;

import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Broker connections use Spring Boot's environment-backed spring.rabbitmq configuration. */
@Configuration(proxyBeanMethods = false)
public class RabbitConfiguration {

    @Bean
    public Jackson2JsonMessageConverter rabbitMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }
}
