package com.yolovision.service;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

class ByteRangeTest {

    private static final long SIZE = 10_000;
    private static final String ETAG = "\"abc123\"";

    private static ByteRange resolve(String header) {
        return ByteRange.resolve(header, null, ETAG, SIZE);
    }

    @Test
    void missingOrBlankHeaderMeansTheFullObject() {
        assertThat(resolve(null)).isEqualTo(new ByteRange.Full(SIZE));
        assertThat(resolve("  ")).isEqualTo(new ByteRange.Full(SIZE));
    }

    @ParameterizedTest
    @CsvSource({
        "bytes=0-1023, 0, 1023",          // first kilobyte
        "bytes=0-0, 0, 0",                // first byte
        "bytes=5000-5999, 5000, 5999",    // middle
        "bytes=9999-9999, 9999, 9999",    // last byte
        "bytes=1024-, 1024, 9999",        // open-ended
        "bytes=9000-20000, 9000, 9999",   // end clamped to the object
        "bytes=-2048, 7952, 9999",        // suffix
        "bytes=-1, 9999, 9999",           // last byte as suffix
        "bytes=-50000, 0, 9999",          // suffix longer than the object
        "bytes= 10-20 , 10, 20"           // optional whitespace
    })
    void singleRangesResolveToInclusiveBounds(String header, long start, long end) {
        ByteRange range = resolve(header);
        assertThat(range).isEqualTo(new ByteRange.Partial(start, end, SIZE));
        ByteRange.Partial partial = (ByteRange.Partial) range;
        assertThat(partial.length()).isEqualTo(end - start + 1);
        assertThat(partial.contentRange()).isEqualTo("bytes " + start + "-" + end + "/" + SIZE);
    }

    @ParameterizedTest
    @ValueSource(strings = {"bytes=10000-", "bytes=10000-10010", "bytes=999999-", "bytes=-0"})
    void rangesBeyondTheObjectAreUnsatisfiable(String header) {
        ByteRange range = resolve(header);
        assertThat(range).isEqualTo(new ByteRange.Unsatisfiable(SIZE));
        assertThat(((ByteRange.Unsatisfiable) range).contentRange()).isEqualTo("bytes */10000");
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "bytes=abc", "bytes=1-2-3", "bytes=-", "items=0-10", "0-10", "bytes=20-10",
        "bytes=0-10,20-30", "bytes=0-1, -5", "bytes=1234567890123456789-", "bytes=0x10-20"
    })
    void malformedUnsupportedOrMultiRangeHeadersAreIgnored(String header) {
        // RFC 9110 permits ignoring such headers; multipart/byteranges is never produced.
        assertThat(resolve(header)).isEqualTo(new ByteRange.Full(SIZE));
    }

    @Test
    void ifRangeHonoursOnlyAStrongMatchingEtag() {
        assertThat(ByteRange.resolve("bytes=0-9", ETAG, ETAG, SIZE)).isEqualTo(new ByteRange.Partial(0, 9, SIZE));
        assertThat(ByteRange.resolve("bytes=0-9", "\"other\"", ETAG, SIZE)).isEqualTo(new ByteRange.Full(SIZE));
        assertThat(ByteRange.resolve("bytes=0-9", "W/" + ETAG, ETAG, SIZE)).isEqualTo(new ByteRange.Full(SIZE));
        assertThat(ByteRange.resolve("bytes=0-9", "Wed, 21 Oct 2026 07:28:00 GMT", ETAG, SIZE))
                .isEqualTo(new ByteRange.Full(SIZE));
        assertThat(ByteRange.resolve("bytes=0-9", ETAG, null, SIZE)).isEqualTo(new ByteRange.Full(SIZE));
    }

    @Test
    void emptyObjectsNeverProduceARange() {
        assertThat(ByteRange.resolve("bytes=0-1", null, ETAG, 0)).isEqualTo(new ByteRange.Full(0));
    }
}
