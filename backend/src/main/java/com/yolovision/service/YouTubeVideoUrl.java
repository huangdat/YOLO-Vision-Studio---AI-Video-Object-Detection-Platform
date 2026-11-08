package com.yolovision.service;

import java.net.URI;
import java.net.URISyntaxException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Accepts one public YouTube video URL and returns its canonical watch URL. Mirrors the
 * worker's {@code YouTubeDownloader.validate_url}, which revalidates before downloading:
 * playlists, channels, credentials, non-default ports, and other hosts are rejected.
 */
final class YouTubeVideoUrl {

    private static final Set<String> HOSTS = Set.of(
            "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com");
    private static final Pattern VIDEO_ID = Pattern.compile("^[A-Za-z0-9_-]{11}$");

    private YouTubeVideoUrl() {
    }

    /** Returns the canonical URL, or throws IllegalArgumentException with a client-safe reason. */
    static String canonicalize(String value) {
        if (value.chars().anyMatch(character -> Character.isWhitespace(character) || character < 32)) {
            throw new IllegalArgumentException("must not contain whitespace or control characters");
        }
        URI uri;
        try {
            uri = new URI(value);
        } catch (URISyntaxException exception) {
            throw new IllegalArgumentException("must be a valid URL");
        }
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        if (!scheme.equals("https") && !scheme.equals("http")) {
            throw new IllegalArgumentException("must be an http(s) YouTube URL");
        }
        if (uri.getRawUserInfo() != null) {
            throw new IllegalArgumentException("must not contain credentials");
        }
        int defaultPort = scheme.equals("https") ? 443 : 80;
        if (uri.getPort() != -1 && uri.getPort() != defaultPort) {
            throw new IllegalArgumentException("must use the default port");
        }
        String host = uri.getHost() == null ? "" : uri.getHost().toLowerCase(Locale.ROOT);
        String path = uri.getRawPath() == null ? "" : uri.getRawPath();
        List<String> videoIds = queryValues(uri.getRawQuery(), "v");
        if (!queryValues(uri.getRawQuery(), "list").isEmpty() || path.toLowerCase(Locale.ROOT).contains("/playlist")) {
            throw new IllegalArgumentException("must identify a single video, not a playlist");
        }
        String id;
        String[] segments = path.replaceAll("^/+|/+$", "").split("/");
        if (host.equals("youtu.be")) {
            id = segments.length == 1 ? segments[0] : "";
        } else if (HOSTS.contains(host)) {
            if (path.equals("/watch") || path.equals("/watch/")) {
                id = videoIds.size() == 1 ? videoIds.get(0) : "";
            } else {
                id = segments.length == 2 && Set.of("shorts", "embed").contains(segments[0]) ? segments[1] : "";
            }
        } else {
            throw new IllegalArgumentException("must be a supported YouTube video URL");
        }
        if (!VIDEO_ID.matcher(id).matches()) {
            throw new IllegalArgumentException("must identify one valid YouTube video");
        }
        return "https://www.youtube.com/watch?v=" + id;
    }

    private static List<String> queryValues(String rawQuery, String name) {
        List<String> values = new ArrayList<>();
        if (rawQuery == null || rawQuery.isEmpty()) {
            return values;
        }
        for (String pair : rawQuery.split("&")) {
            int separator = pair.indexOf('=');
            String key = URLDecoder.decode(separator < 0 ? pair : pair.substring(0, separator), StandardCharsets.UTF_8);
            if (key.equals(name)) {
                values.add(separator < 0 ? "" : URLDecoder.decode(pair.substring(separator + 1), StandardCharsets.UTF_8));
            }
        }
        return values;
    }
}
