import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import { detectionVideoUrl, probeDetectionVideo } from "../../api/artifacts";
import { toApiError } from "../../api/client";
import { formatDuration } from "../../lib/format";
import { Icon } from "../Icon";

type PlayerState =
  | { kind: "loading" }
  | { kind: "ready"; durationMs: number | null }
  | { kind: "checking" }
  | { kind: "error"; title: string; message: string; retryable: boolean };

/** Media element error codes (HTMLMediaElement.error.code). */
const MEDIA_ERR_NETWORK = 2;

/**
 * Native HTML5 player for the annotated MP4. The browser streams it from the backend with
 * Range requests (seeking works without downloading the whole file). There is no autoplay;
 * a playback failure is explained with the backend's own error code and can be retried
 * without touching the detection job.
 */
export function DetectionVideoPlayer({
  jobId,
  onMissing,
}: {
  jobId: string;
  /** Called when the backend confirms the stored video does not exist. */
  onMissing?: () => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PlayerState>({ kind: "loading" });
  const probe = useRef<AbortController | null>(null);

  useEffect(() => () => probe.current?.abort(), []);

  const handleError = (event: SyntheticEvent<HTMLVideoElement>) => {
    const mediaCode = event.currentTarget.error?.code;
    probe.current?.abort();
    const controller = new AbortController();
    probe.current = controller;
    setState({ kind: "checking" });
    probeDetectionVideo(jobId, controller.signal).then(
      () => {
        if (controller.signal.aborted) return;
        setState(
          mediaCode === MEDIA_ERR_NETWORK
            ? {
                kind: "error",
                title: "Playback was interrupted",
                message: "The network connection dropped while the video was loading.",
                retryable: true,
              }
            : {
                kind: "error",
                title: "This browser could not play the video",
                message:
                  "The video is available but could not be decoded here. You can still download it.",
                retryable: true,
              },
        );
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError = toApiError(error);
        if (apiError.kind === "cancelled") return;
        if (apiError.code === "ARTIFACT_NOT_FOUND") {
          onMissing?.();
          setState({
            kind: "error",
            title: "The detected video is missing",
            message:
              "The job completed, but its video file is not available in storage. Retrying will not restore it.",
            retryable: false,
          });
          return;
        }
        setState({
          kind: "error",
          title:
            apiError.code === "STORAGE_UNAVAILABLE"
              ? "Video storage is temporarily unavailable"
              : "The video could not be loaded",
          message: apiError.message,
          retryable: apiError.retryable || apiError.code === "STORAGE_UNAVAILABLE",
        });
      },
    );
  };

  const retry = () => {
    probe.current?.abort();
    setState({ kind: "loading" });
    setAttempt((value) => value + 1);
  };

  if (state.kind === "error" || state.kind === "checking") {
    return (
      <div className="video-frame video-problem" role={state.kind === "error" ? "alert" : "status"}>
        {state.kind === "checking" ? (
          <p>
            <Icon name="refresh" size={16} className="spin" />
            Checking why the video could not be played…
          </p>
        ) : (
          <>
            <Icon name="alert" size={22} />
            <strong>{state.title}</strong>
            <p>{state.message}</p>
            {state.retryable && (
              <button type="button" className="button-secondary" onClick={retry}>
                <Icon name="refresh" size={14} />
                Retry playback
              </button>
            )}
          </>
        )}
      </div>
    );
  }

  return (
    <div className="video-frame">
      <video
        key={attempt}
        className="detection-video"
        src={detectionVideoUrl(jobId)}
        controls
        preload="metadata"
        playsInline
        aria-label="Annotated detection video"
        onLoadedMetadata={(event) => {
          const seconds = event.currentTarget.duration;
          setState({
            kind: "ready",
            durationMs: Number.isFinite(seconds) ? Math.round(seconds * 1000) : null,
          });
        }}
        onError={handleError}
      >
        Your browser does not support HTML5 video. Use the download button instead.
      </video>
      {state.kind === "loading" && (
        <p className="video-loading" role="status">
          <Icon name="refresh" size={15} className="spin" />
          Loading video…
        </p>
      )}
      {state.kind === "ready" && state.durationMs !== null && (
        <p className="video-meta">Duration {formatDuration(state.durationMs)}</p>
      )}
    </div>
  );
}
