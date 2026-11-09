package com.yolovision.storage;

/** Metadata of a stored object as reported by the storage service, never invented. */
public record StoredObject(String key, long size, String contentType, String etag) {
}
