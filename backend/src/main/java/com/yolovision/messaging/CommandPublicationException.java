package com.yolovision.messaging;

/** The broker did not durably accept a command; the outbox row stays pending for retry. */
public class CommandPublicationException extends Exception {

    public CommandPublicationException(String message) {
        super(message);
    }

    public CommandPublicationException(String message, Throwable cause) {
        super(message, cause);
    }
}
