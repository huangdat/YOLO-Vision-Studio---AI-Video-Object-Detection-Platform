package com.yolovision.storage;

import com.yolovision.exception.StorageObjectNotFoundException;
import com.yolovision.exception.StorageUnavailableException;
import java.io.ByteArrayInputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Test double for {@link ObjectStorage}. It records every ranged open and whether each stream was
 * closed, can simulate an outage, and can fail a stream after a number of bytes.
 */
public class InMemoryObjectStorage implements ObjectStorage {

    public record Open(String key, long offset, long length, AtomicBoolean closed) {
    }

    private final Map<String, byte[]> objects = new ConcurrentHashMap<>();
    private final Map<String, String> types = new ConcurrentHashMap<>();
    private final List<Open> opens = new CopyOnWriteArrayList<>();
    private volatile boolean unavailable;
    private volatile long failAfterBytes = -1;

    public void put(String key, byte[] bytes, String contentType) {
        objects.put(key, bytes.clone());
        types.put(key, contentType);
    }

    public void reset() {
        objects.clear();
        types.clear();
        opens.clear();
        unavailable = false;
        failAfterBytes = -1;
    }

    public void setUnavailable(boolean unavailable) {
        this.unavailable = unavailable;
    }

    /** Every subsequently opened stream throws IOException after this many bytes. */
    public void failStreamsAfter(long bytes) {
        this.failAfterBytes = bytes;
    }

    public List<Open> opens() {
        return List.copyOf(opens);
    }

    @Override
    public StoredObject stat(String key) {
        byte[] bytes = lookup(key);
        return new StoredObject(key, bytes.length, types.get(key), "etag-" + Arrays.hashCode(bytes));
    }

    @Override
    public InputStream open(String key, long offset, long length) {
        byte[] bytes = lookup(key);
        AtomicBoolean closed = new AtomicBoolean();
        opens.add(new Open(key, offset, length, closed));
        long limit = failAfterBytes;
        InputStream window = new ByteArrayInputStream(bytes, (int) offset, (int) length);
        return new FilterInputStream(window) {
            private long served;

            @Override
            public int read() throws IOException {
                byte[] one = new byte[1];
                return read(one, 0, 1) < 0 ? -1 : one[0] & 0xff;
            }

            @Override
            public int read(byte[] buffer, int off, int len) throws IOException {
                if (limit >= 0 && served >= limit) {
                    throw new IOException("simulated storage failure");
                }
                int allowed = limit >= 0 ? (int) Math.min(len, limit - served) : len;
                int read = super.read(buffer, off, allowed);
                if (read > 0) {
                    served += read;
                }
                return read;
            }

            @Override
            public void close() throws IOException {
                closed.set(true);
                super.close();
            }
        };
    }

    private byte[] lookup(String key) {
        if (unavailable) {
            throw new StorageUnavailableException();
        }
        byte[] bytes = objects.get(key);
        if (bytes == null) {
            throw new StorageObjectNotFoundException();
        }
        return bytes;
    }
}
