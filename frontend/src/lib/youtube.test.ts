import { describe, expect, it } from "vitest";
import { checkYouTubeUrl } from "./youtube";

/** Same cases as the backend's YouTubeVideoUrlTest, so the frontend is never stricter. */
describe("checkYouTubeUrl", () => {
  it.each([
    "https://www.youtube.com/watch?v=abcdefghijk",
    "http://youtube.com/watch?v=abcdefghijk",
    "https://m.youtube.com/watch?feature=share&v=abcdefghijk&t=42",
    "https://music.youtube.com/watch?v=abcdefghijk",
    "https://youtu.be/abcdefghijk",
    "https://youtu.be/abcdefghijk?t=10",
    "https://www.youtube.com/shorts/abcdefghijk",
    "https://www.youtube.com/embed/abcdefghijk",
    "https://WWW.YOUTUBE.COM/watch?v=abcdefghijk",
    "https://www.youtube.com:443/watch?v=abcdefghijk",
    "  https://www.youtube.com/watch?v=abcdefghijk  ",
  ])("accepts the single-video URL %s", (url) => {
    expect(checkYouTubeUrl(url)).toEqual({ valid: true, videoId: "abcdefghijk" });
  });

  it.each([
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
    "not a url",
    "",
  ])("rejects %s", (url) => {
    expect(checkYouTubeUrl(url).valid).toBe(false);
  });

  it.each([
    ["", "Enter a YouTube video URL."],
    ["https://www.youtube.com/playlist?list=PLabc", "Playlists are not supported. Use a single video URL."],
    ["https://user:pass@www.youtube.com/watch?v=abcdefghijk", "The URL must not contain credentials."],
    ["https://www.youtube.com:8080/watch?v=abcdefghijk", "The URL must use the default port."],
    ["https://evil.example/watch?v=abcdefghijk", "Only YouTube video URLs are supported."],
    ["ftp://www.youtube.com/watch?v=abcdefghijk", "Only http(s) YouTube URLs are supported."],
    ["https://youtu.be/abc", "The URL must identify a single YouTube video."],
  ])("explains why %s is rejected", (url, message) => {
    expect(checkYouTubeUrl(url)).toEqual({ valid: false, message });
  });
});
