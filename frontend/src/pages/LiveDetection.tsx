import { useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { listModels } from "../api/models";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Alert, Disclosure, ErrorState, LoadingSkeleton } from "../components/StateViews";
import { ClassSelector } from "../components/workspace/ClassSelector";
import { ConfidenceControl, ImageSizeSelector } from "../components/workspace/DetectionSettings";
import { useApiResource } from "../hooks/useApiResource";
import { useLiveDetection, type LiveDependencies } from "../hooks/useLiveDetection";
import { VEHICLE_CLASS_IDS } from "../lib/cocoClasses";
import { DEFAULT_CONFIDENCE, parseConfidence } from "../lib/detectionForm";
import { sizeName } from "../lib/format";
import { LIVE_DEFAULT_IMAGE_SIZE, LIVE_IMAGE_SIZES } from "../lib/liveProtocol";
import type { ModelConfig } from "../types/models";

/** Live Detection supports only lightweight (Nano) detection models; the server enforces it too. */
export function liveModels(models: ModelConfig[]): ModelConfig[] {
  return models.filter((model) => model.modelSize === "n" && model.taskType === "DETECT");
}

export function defaultLiveModel(models: ModelConfig[]): string {
  const usable = liveModels(models).filter((model) => model.enabled);
  return (usable.find((model) => model.modelKey === "yolo11n") ?? usable[0])?.modelKey ?? "";
}

const formatMetric = (value: number | null, digits: number, unit: string) =>
  value === null ? "—" : `${value.toFixed(digits)}${unit}`;

export function LiveDetection({ dependencies }: { dependencies?: Partial<LiveDependencies> }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const live = useLiveDetection(videoRef, canvasRef, dependencies);
  const catalog = useApiResource((signal) => listModels({}, signal), "live-models");
  const [pickedModel, setPickedModel] = useState("");
  const [classes, setClasses] = useState<number[]>([...VEHICLE_CLASS_IDS]);
  const [confidence, setConfidence] = useState(DEFAULT_CONFIDENCE.toFixed(2));
  const [imageSize, setImageSize] = useState<number>(LIVE_DEFAULT_IMAGE_SIZE);
  const cameraSelectId = useId();
  const modelSelectId = useId();

  const models = useMemo(() => liveModels(catalog.data?.models ?? []), [catalog.data]);
  const modelKey = models.some((model) => model.modelKey === pickedModel && model.enabled)
    ? pickedModel : defaultLiveModel(catalog.data?.models ?? []);
  const parsedConfidence = parseConfidence(confidence);
  const busy = live.phase !== "idle";
  const running = live.phase === "running";
  const canStart = !busy && modelKey !== "" && parsedConfidence !== null && classes.length > 0;
  const startHint = modelKey === ""
    ? "No enabled Nano detection model is available."
    : classes.length === 0
      ? "Select at least one object class."
      : parsedConfidence === null
        ? "Enter a confidence between 0 and 1."
        : null;

  const start = () => {
    if (!canStart || parsedConfidence === null) return;
    void live.start({ modelKey, confidence: parsedConfidence, imageSize, classes });
  };

  const statusText = live.phase === "starting"
    ? live.connection === "connecting" ? "Connecting to the detector…" : "Starting the camera…"
    : running ? "Detecting live" : "Camera off";

  return (
    <>
      <PageHeader
        title="Live Detection"
        description="Detect objects in real time using your webcam. Frames are analysed in memory and never stored."
      />

      <section className="card live-card" aria-labelledby="live-view-title">
        <h2 id="live-view-title" className="visually-hidden">Live camera view</h2>
        <div className={`live-stage ${busy ? "is-active" : ""}`}>
          <video
            ref={videoRef}
            className={`live-video ${live.mirrored ? "is-mirrored" : ""}`}
            muted
            playsInline
            aria-label="Live camera preview"
          />
          <canvas ref={canvasRef} className="live-overlay" aria-hidden="true" />
          {!busy && (
            <div className="live-placeholder">
              <span className="state-icon">
                <Icon name="camera" size={26} />
              </span>
              <p>The camera is off. It turns on only when you start Live Detection.</p>
            </div>
          )}
          <span className={`live-indicator ${busy ? "on" : ""}`} role="status" aria-live="polite">
            <span className="live-indicator-dot" aria-hidden="true" />
            {statusText}
          </span>
        </div>

        <dl className="live-metrics" aria-label="Live detection metrics">
          <div><dt>Processed FPS</dt><dd>{formatMetric(live.metrics.fps, 1, "")}</dd></div>
          <div><dt>Latency</dt><dd>{formatMetric(live.metrics.latencyMs, 0, " ms")}</dd></div>
          <div><dt>Inference</dt><dd>{formatMetric(live.metrics.inferenceMs, 0, " ms")}</dd></div>
          <div><dt>Frames</dt><dd>{live.metrics.processed}</dd></div>
          <div><dt>Dropped</dt><dd>{live.metrics.dropped}</dd></div>
          <div><dt>Objects</dt><dd>{running ? live.metrics.detections : "—"}</dd></div>
        </dl>

        {live.notice && (
          <Alert tone={live.notice.tone} role={live.notice.tone === "error" ? "alert" : "status"}>
            <p>{live.notice.text}</p>
          </Alert>
        )}

        <div className="live-actions">
          <button type="button" className="button-primary button-large" onClick={start} disabled={!canStart}>
            <Icon name="play" size={17} />
            {live.phase === "starting" ? "Starting…" : "Start Live Detection"}
          </button>
          <button type="button" className="button-secondary button-large" onClick={live.stop} disabled={!busy}>
            <Icon name="close" size={17} />
            Stop
          </button>
          {startHint && !busy && <p className="field-hint live-start-hint">{startHint}</p>}
        </div>
      </section>

      <section className="card live-settings" aria-labelledby="live-settings-title">
        <h2 id="live-settings-title" className="card-title">Settings</h2>
        <div className="settings-grid">
          <div className="form-field">
            <label htmlFor={cameraSelectId} className="field-label">Camera</label>
            <select
              id={cameraSelectId}
              className="select-input"
              value={live.cameraId}
              disabled={busy || live.cameras.length === 0}
              onChange={(event) => live.setCameraId(event.target.value)}
            >
              {live.cameras.length === 0 && <option value="">Default camera</option>}
              {live.cameras.map((camera) => (
                <option key={camera.deviceId} value={camera.deviceId}>{camera.label}</option>
              ))}
            </select>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={live.mirrored}
                onChange={(event) => live.setMirrored(event.target.checked)}
              />
              Mirror preview
            </label>
          </div>

          <div className="form-field">
            <label htmlFor={modelSelectId} className="field-label">AI model</label>
            {catalog.status === "loading" && <LoadingSkeleton rows={1} label="Loading models" />}
            {catalog.status === "error" && (
              <ErrorState title="The model catalog could not be loaded" error={catalog.error} onRetry={catalog.reload} />
            )}
            {catalog.status === "success" && (
              <select
                id={modelSelectId}
                className="select-input"
                value={modelKey}
                disabled={busy || models.length === 0}
                onChange={(event) => setPickedModel(event.target.value)}
              >
                {modelKey === "" && <option value="">No enabled Nano model</option>}
                {models.map((model) => (
                  <option key={model.modelKey} value={model.modelKey} disabled={!model.enabled}>
                    {model.version} {sizeName(model.modelSize)} ({model.modelKey}){model.enabled ? "" : " — disabled"}
                  </option>
                ))}
              </select>
            )}
            <p className="field-hint">
              Lightweight Nano models only. Enabled does not mean prepared: the server reports
              it if a model's weights still need to be prepared. <Link to="/models" className="text-link">Browse models</Link>
            </p>
          </div>
        </div>

        <div className="live-classes">
          <ClassSelector selected={classes} disabled={busy} onChange={setClasses} />
        </div>

        <Disclosure
          label="Advanced settings"
          summary={`Confidence ${parsedConfidence ?? "invalid"} · Image size ${imageSize} px`}
          className="advanced-settings"
          forceOpen={parsedConfidence === null}
        >
          <div className="settings-grid">
            <ConfidenceControl
              value={confidence}
              disabled={busy}
              error={parsedConfidence === null ? "Enter a value from 0 to 1 with at most three decimals." : undefined}
              onChange={setConfidence}
            />
            <ImageSizeSelector
              value={imageSize}
              disabled={busy}
              sizes={LIVE_IMAGE_SIZES}
              defaultSize={LIVE_DEFAULT_IMAGE_SIZE}
              onChange={setImageSize}
            />
          </div>
        </Disclosure>
        <p className="field-hint">
          Real-time speed depends on your computer: on a CPU, a few frames per second is expected.
          Settings apply when a session starts.
        </p>
      </section>
    </>
  );
}
