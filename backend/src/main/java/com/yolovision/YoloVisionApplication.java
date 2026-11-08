package com.yolovision;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class YoloVisionApplication {

    public static void main(String[] args) {
        SpringApplication.run(YoloVisionApplication.class, args);
    }
}
