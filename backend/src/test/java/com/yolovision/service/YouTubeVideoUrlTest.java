package com.yolovision.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class YouTubeVideoUrlTest {

    @ParameterizedTest
    @ValueSource(strings = {
        "https://www.youtube.com/watch?v=abcdefghijk",
        "http://youtube.com/watch?v=abcdefghijk",
        "https://m.youtube.com/watch?feature=share&v=abcdefghijk&t=42",
        "https://music.youtube.com/watch?v=abcdefghijk",
        "https://youtu.be/abcdefghijk",
        "https://youtu.be/abcdefghijk?t=10",
        "https://www.youtube.com/shorts/abcdefghijk",
        "https://www.youtube.com/embed/abcdefghijk",
        "https://WWW.YOUTUBE.COM/watch?v=abcdefghijk",
        "https://www.youtube.com:443/watch?v=abcdefghijk"
    })
    void singleVideoUrlsAreCanonicalised(String url) {
        assertThat(YouTubeVideoUrl.canonicalize(url)).isEqualTo("https://www.youtube.com/watch?v=abcdefghijk");
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "https://www.youtube.com/playlist?list=PLabc",
        "https://www.youtube.com/watch?v=abcdefghijk&list=PLabc",
        "https://www.youtube.com/watch?v=abcdefghijk&v=bcdefghijkl",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/@channel",
        "https://www.youtube.com/channel/UC123",
        "https://youtu.be/",
        "https://youtu.be/abc",
        "https://youtu.be/abcdefghijk/extra",
        "https://www.youtube.com/shorts/abcdefghij!",
        "https://www.youtube.com.evil.example/watch?v=abcdefghijk",
        "https://evil.example/watch?v=abcdefghijk",
        "https://user:pass@www.youtube.com/watch?v=abcdefghijk",
        "https://www.youtube.com:8080/watch?v=abcdefghijk",
        "ftp://www.youtube.com/watch?v=abcdefghijk",
        "file:///etc/passwd",
        "/data/inputs/clip.mp4",
        "C:\\videos\\clip.mp4",
        "https://www.youtube.com/watch?v=abc defghijk",
        "not a url"
    })
    void everythingElseIsRejected(String url) {
        assertThatThrownBy(() -> YouTubeVideoUrl.canonicalize(url)).isInstanceOf(IllegalArgumentException.class);
    }
}
