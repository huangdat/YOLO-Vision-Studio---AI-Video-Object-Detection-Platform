package com.yolovision.service;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Resolves a {@code Range} request header against an object size (RFC 9110, section 14).
 * Exactly one byte range is supported:
 * <ul>
 *   <li>{@code bytes=a-b}, {@code bytes=a-}, and {@code bytes=-n} produce 206 (end clamped to the size);</li>
 *   <li>a range starting at or beyond the size, or {@code bytes=-0}, is unsatisfiable (416);</li>
 *   <li>a missing, malformed, non-{@code bytes}, or multi-range header is ignored (200 with the full
 *       body), which RFC 9110 permits; multipart/byteranges responses are never produced;</li>
 *   <li>an {@code If-Range} value that does not equal the current strong ETag also yields the full body.</li>
 * </ul>
 */
public sealed interface ByteRange {

    /** No usable range: send the complete object with 200. */
    record Full(long size) implements ByteRange {
    }

    /** Send bytes {@code start..end} (inclusive) with 206. */
    record Partial(long start, long end, long size) implements ByteRange {

        public long length() {
            return end - start + 1;
        }

        public String contentRange() {
            return "bytes " + start + "-" + end + "/" + size;
        }
    }

    /** The range cannot be satisfied: answer 416 with {@code Content-Range: bytes *}{@code /size}. */
    record Unsatisfiable(long size) implements ByteRange {

        public String contentRange() {
            return "bytes */" + size;
        }
    }

    // Up to 18 digits keeps every value inside a long without overflow checks.
    Pattern SINGLE = Pattern.compile("^bytes=[ \\t]*(\\d{0,18})-(\\d{0,18})[ \\t]*$");

    static ByteRange resolve(String rangeHeader, String ifRange, String etag, long size) {
        if (rangeHeader == null || rangeHeader.isBlank() || size <= 0) {
            return new Full(size);
        }
        if (ifRange != null && !ifRange.isBlank() && (etag == null || !isStrongMatch(ifRange.strip(), etag))) {
            return new Full(size);
        }
        Matcher matcher = SINGLE.matcher(rangeHeader.strip());
        if (!matcher.matches()) {
            return new Full(size); // malformed, other unit, or multiple ranges
        }
        String first = matcher.group(1);
        String last = matcher.group(2);
        if (first.isEmpty() && last.isEmpty()) {
            return new Full(size);
        }
        if (first.isEmpty()) {
            long suffix = Long.parseLong(last);
            if (suffix == 0) {
                return new Unsatisfiable(size);
            }
            return new Partial(Math.max(0, size - suffix), size - 1, size);
        }
        long start = Long.parseLong(first);
        if (!last.isEmpty() && Long.parseLong(last) < start) {
            return new Full(size); // invalid range-spec: ignored
        }
        if (start >= size) {
            return new Unsatisfiable(size);
        }
        long end = last.isEmpty() ? size - 1 : Math.min(Long.parseLong(last), size - 1);
        return new Partial(start, end, size);
    }

    private static boolean isStrongMatch(String ifRange, String etag) {
        // Weak validators and dates never match: the full representation is sent instead.
        return !ifRange.startsWith("W/") && ifRange.equals(etag);
    }
}
