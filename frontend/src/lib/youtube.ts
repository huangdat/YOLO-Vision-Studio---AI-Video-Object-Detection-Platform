/**
 * Preliminary YouTube URL check for immediate feedback. It mirrors the backend's
 * YouTubeVideoUrl rules (single video; watch, youtu.be, shorts, or embed forms; no
 * playlists, credentials, or non-default ports) so it is never stricter than the API.
 * The backend stays authoritative and canonicalises the URL itself.
 */
const HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"]);
const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

export type YouTubeCheck = { valid: true; videoId: string } | { valid: false; message: string };

export function checkYouTubeUrl(input: string): YouTubeCheck {
  const value = input.trim();
  if (!value) return { valid: false, message: "Enter a YouTube video URL." };
  if (/\s|[\u0000-\u001f]/.test(value)) {
    return { valid: false, message: "The URL must not contain spaces." };
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return { valid: false, message: "Enter a full URL, such as https://www.youtube.com/watch?v=…" };
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return { valid: false, message: "Only http(s) YouTube URLs are supported." };
  }
  if (url.username || url.password) {
    return { valid: false, message: "The URL must not contain credentials." };
  }
  const defaultPort = url.protocol === "https:" ? "443" : "80";
  if (url.port && url.port !== defaultPort) {
    return { valid: false, message: "The URL must use the default port." };
  }
  const host = url.hostname.toLowerCase();
  if (host !== "youtu.be" && !HOSTS.has(host)) {
    return { valid: false, message: "Only YouTube video URLs are supported." };
  }
  if (url.searchParams.has("list") || url.pathname.toLowerCase().includes("/playlist")) {
    return { valid: false, message: "Playlists are not supported. Use a single video URL." };
  }
  const segments = url.pathname.replace(/^\/+|\/+$/g, "").split("/");
  let id = "";
  if (host === "youtu.be") {
    id = segments.length === 1 ? segments[0] : "";
  } else if (url.pathname === "/watch" || url.pathname === "/watch/") {
    const ids = url.searchParams.getAll("v");
    id = ids.length === 1 ? ids[0] : "";
  } else if (segments.length === 2 && (segments[0] === "shorts" || segments[0] === "embed")) {
    id = segments[1];
  }
  if (!VIDEO_ID.test(id)) {
    return { valid: false, message: "The URL must identify a single YouTube video." };
  }
  return { valid: true, videoId: id };
}
