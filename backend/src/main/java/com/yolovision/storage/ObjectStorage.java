package com.yolovision.storage;

import com.yolovision.exception.StorageObjectNotFoundException;
import com.yolovision.exception.StorageUnavailableException;
import java.io.InputStream;

/**
 * Minimal read operations on the private artifact bucket. Implementations never load whole
 * objects into memory: {@link #open} streams exactly the requested byte window.
 */
public interface ObjectStorage {

    /**
     * Returns the object's metadata.
     *
     * @throws StorageObjectNotFoundException when the object or bucket does not exist
     * @throws StorageUnavailableException when storage cannot be reached or is not configured
     */
    StoredObject stat(String key);

    /**
     * Opens {@code length} bytes starting at {@code offset}. The caller must close the stream.
     *
     * @throws StorageObjectNotFoundException when the object or bucket does not exist
     * @throws StorageUnavailableException when storage cannot be reached or is not configured
     */
    InputStream open(String key, long offset, long length);
}
