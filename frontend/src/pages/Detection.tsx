import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toApiError, type ApiError } from "../api/client";
import { createDetection } from "../api/detections";
import { getModelVersions, listModels } from "../api/models";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Alert, Disclosure, EmptyState, ErrorState, LoadingSkeleton } from "../components/StateViews";
import { ClassSelector } from "../components/workspace/ClassSelector";
import { ConfidenceControl, ImageSizeSelector } from "../components/workspace/DetectionSettings";
import { ModelSelector } from "../components/workspace/ModelSelector";
import { VideoSourceField } from "../components/workspace/VideoSourceField";
import { useApiResource } from "../hooks/useApiResource";
import {
  initialFormState,
  parseConfidence,
  toRequest,
  validateForm,
  type DetectionFormState,
  type FormErrors,
  type FormField,
} from "../lib/detectionForm";
import {
  availableVersions,
  choiceForVersion,
  reconcileChoice,
  resolveModel,
  type ModelChoice,
} from "../lib/modelSelection";
import type { DetectionJobAccepted } from "../types/detections";

interface Banner {
  tone: "error" | "warning";
  title: string;
  message: string;
  showHistory?: boolean;
  offerReload?: boolean;
}

/** Location state handed to the job page after a successful submission. */
export interface SubmittedState {
  submitted: DetectionJobAccepted;
}

async function loadCatalog(signal: AbortSignal) {
  const [catalog, versions] = await Promise.all([listModels({}, signal), getModelVersions(signal)]);
  return { models: catalog.models, versions: versions.versions };
}

/**
 * Maps a failed submission to user guidance. Only explicit backend rejections prove that
 * nothing was created (the job and its outbox message are written atomically); anything
 * else is ambiguous, so the user is sent to History instead of retrying automatically.
 */
export function submissionBanner(error: ApiError): Banner {
  const definite = (title: string, message: string, offerReload = false): Banner => ({
    tone: "error",
    title,
    message,
    offerReload,
  });
  switch (error.code) {
    case "INVALID_DETECTION_REQUEST":
      return definite(
        "Some settings were rejected",
        "Correct the highlighted fields and submit again. No job was created.",
      );
    case "MALFORMED_REQUEST":
      return definite("The request was not accepted", `${error.message} No job was created.`);
    case "MODEL_NOT_FOUND":
      return definite(
        "The model is no longer registered",
        "Reload the model list and choose another model. No job was created.",
        true,
      );
    case "MODEL_DISABLED":
      return definite(
        "The model is disabled",
        "An administrator has disabled this model. Reload the model list and choose an enabled model. No job was created.",
        true,
      );
    case "MODEL_NOT_SUPPORTED":
      return definite(
        "The model is not supported",
        "This model is not an object detection model. Choose another model. No job was created.",
        true,
      );
    case "PAYLOAD_TOO_LARGE":
      return definite("The request is too large", "Reduce the request size and try again. No job was created.");
    case "SERVICE_UNAVAILABLE":
      return definite(
        "The service is temporarily unavailable",
        "The backend could not store the job, so nothing was created. Try again in a moment.",
      );
    default:
      // Any other 4xx is still an explicit refusal (for example a proxy or CORS 403).
      if (error.kind === "http" && error.status !== undefined && error.status < 500) {
        return definite("The request was rejected", `${error.message} No job was created.`);
      }
      return {
        tone: "warning",
        title: "The submission result is unknown",
        message:
          error.kind === "network" || error.kind === "timeout"
            ? "The connection failed before the backend confirmed the job. It may still have been created. Check Detection History before submitting again."
            : "The backend did not confirm the job, but it may still have been created. Check Detection History before submitting again.",
        showHistory: true,
      };
  }
}

const FORM_FIELDS: readonly FormField[] = ["videoUrl", "modelKey", "confidence", "imageSize", "classes"];

/**
 * Splits backend field errors (public keys: videoUrl, modelKey, confidence, imageSize,
 * classes) into per-field messages; anything else is kept for the banner.
 */
export function serverFieldErrors(error: ApiError): { fields: FormErrors; other: string[] } {
  const fields: FormErrors = {};
  const other: string[] = [];
  if (error.code !== "INVALID_DETECTION_REQUEST") return { fields, other };
  for (const [key, message] of Object.entries(error.fieldErrors)) {
    const field = FORM_FIELDS.find((name) => name === key.replace(/[[.].*$/, ""));
    if (field) fields[field] ??= `Rejected by the server: ${message}.`;
    else other.push(`${key}: ${message}.`);
  }
  return { fields, other };
}

export function Detection() {
  const navigate = useNavigate();
  const catalog = useApiResource(loadCatalog, "workspace-catalog");
  const [form, setForm] = useState<DetectionFormState>(initialFormState);
  const [picked, setPicked] = useState<ModelChoice | null>(null);
  const [touched, setTouched] = useState<Partial<Record<FormField, boolean>>>({});
  const [attempted, setAttempted] = useState(false);
  const [serverErrors, setServerErrors] = useState<FormErrors>({});
  const [banner, setBanner] = useState<Banner | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const models = catalog.data?.models ?? [];
  const versionOrder = catalog.data?.versions ?? [];
  // The user's pick while it is still registered; otherwise the catalog default. Derived
  // during render so a (re)loaded catalog never shows a stale or empty selection.
  const choice = catalog.data ? reconcileChoice(models, versionOrder, picked) : null;

  const model = resolveModel(models, choice);
  const versions = availableVersions(models, versionOrder);
  const clientErrors = validateForm(form, model);
  const visible = (field: FormField) =>
    serverErrors[field] ?? (touched[field] || attempted ? clientErrors[field] : undefined);
  const catalogReady = catalog.status === "success" && models.length > 0;
  const enabledCount = models.filter((item) => item.enabled).length;

  const update = <K extends keyof DetectionFormState>(field: K, value: DetectionFormState[K]) => {
    setForm((current) => ({ ...current, [field]: value }));
    setServerErrors(({ [field as FormField]: _removed, ...rest }) => rest);
  };
  const changeChoice = (next: ModelChoice | null) => {
    setPicked(next);
    setServerErrors(({ modelKey: _removed, ...rest }) => rest);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    // Synchronous guard: rapid clicks or Enter plus click never produce two requests.
    if (inFlight.current) return;
    setAttempted(true);
    if (!model || Object.keys(clientErrors).length > 0) {
      setBanner(null);
      window.requestAnimationFrame(() =>
        formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(),
      );
      return;
    }
    inFlight.current = true;
    setSubmitting(true);
    setBanner(null);
    setServerErrors({});
    try {
      const accepted = await createDetection(toRequest(form, model));
      const state: SubmittedState = { submitted: accepted };
      navigate(`/detections/${accepted.jobId}`, { state });
    } catch (error: unknown) {
      if (!mounted.current) return;
      const apiError = toApiError(error);
      const { fields, other } = serverFieldErrors(apiError);
      const next = submissionBanner(apiError);
      setBanner(other.length > 0 ? { ...next, message: `${next.message} ${other.join(" ")}` } : next);
      setServerErrors(fields);
    } finally {
      inFlight.current = false;
      if (mounted.current) setSubmitting(false);
    }
  };

  const advancedError = Boolean(visible("confidence") || visible("imageSize"));
  const problems = Object.keys(clientErrors).length;
  const statusMessage = submitting
    ? "Submitting the detection job…"
    : !catalogReady
      ? "A registered model is needed before submitting."
      : model && !model.enabled
        ? "The selected model is disabled and cannot be submitted."
        : problems === 0
          ? "Ready to start. The job runs in the background and you will follow its progress next."
          : attempted
            ? `${problems} item${problems === 1 ? "" : "s"} to fix before starting`
            : "Complete the steps above to start.";

  return (
    <>
      <PageHeader
        title="New detection"
        description="Detect objects in a YouTube video with a YOLO model. Paste a link, choose a model, and start."
      />

      <form ref={formRef} className="card workspace" onSubmit={submit} noValidate aria-busy={submitting}>
        <section className="step" aria-labelledby="source-title">
          <StepHeading number={1} id="source-title" title="Add your video" />
          <VideoSourceField
            value={form.videoUrl}
            error={visible("videoUrl")}
            disabled={submitting}
            onChange={(value) => update("videoUrl", value)}
            onBlur={() => setTouched((current) => ({ ...current, videoUrl: true }))}
          />
        </section>

        <section className="step" aria-labelledby="model-title">
          <StepHeading
            number={2}
            id="model-title"
            title="Choose a model"
            aside={
              <Link to="/models" className="text-link">
                Browse models
              </Link>
            }
          />
          {catalog.status === "loading" && <LoadingSkeleton rows={3} label="Loading the model catalog" />}
          {catalog.status === "error" && (
            <ErrorState
              title="The model catalog could not be loaded"
              error={catalog.error}
              onRetry={catalog.reload}
            />
          )}
          {catalog.status === "success" && models.length === 0 && (
            <EmptyState icon="models" title="No models are registered.">
              <p>Detection jobs need a registered model.</p>
              <button type="button" className="button-secondary" onClick={catalog.reload}>
                <Icon name="refresh" size={15} />
                Reload models
              </button>
            </EmptyState>
          )}
          {catalogReady && (
            <>
              {enabledCount === 0 && (
                <Alert tone="warning" role="status" title="No models are currently available for detection.">
                  <p>
                    Please ask an administrator to enable a model. Setup steps are in{" "}
                    <code>docs/yolo-model-management.md</code>.
                  </p>
                </Alert>
              )}
              <ModelSelector
                models={models}
                versions={versions}
                choice={choice}
                selected={model}
                disabled={submitting}
                error={!model ? visible("modelKey") : serverErrors.modelKey}
                onVersionChange={(version) => changeChoice(choiceForVersion(models, version, choice?.size))}
                onSizeChange={(size) => changeChoice(choice ? { ...choice, size } : null)}
              />
            </>
          )}
        </section>

        <section className="step" aria-labelledby="settings-title">
          <StepHeading number={3} id="settings-title" title="Detection settings" />
          <ClassSelector
            selected={form.classes}
            error={visible("classes")}
            disabled={submitting}
            onChange={(classes) => {
              update("classes", classes);
              setTouched((current) => ({ ...current, classes: true }));
            }}
          />
          <Disclosure
            label="Advanced settings"
            summary={`Confidence ${parseConfidence(form.confidence) ?? "invalid"} · Image size ${form.imageSize} px`}
            forceOpen={advancedError}
            className="advanced-settings"
          >
            <div className="settings-grid">
              <ConfidenceControl
                value={form.confidence}
                error={visible("confidence")}
                disabled={submitting}
                onChange={(value) => {
                  update("confidence", value);
                  setTouched((current) => ({ ...current, confidence: true }));
                }}
              />
              <div>
                <ImageSizeSelector
                  value={form.imageSize}
                  disabled={submitting}
                  onChange={(value) => update("imageSize", value)}
                />
                {visible("imageSize") && (
                  <p className="field-error" role="alert">
                    {visible("imageSize")}
                  </p>
                )}
              </div>
            </div>
          </Disclosure>
        </section>

        <section className="step step-submit" aria-labelledby="start-title">
          <StepHeading number={4} id="start-title" title="Start processing" />
          {banner && (
            <Alert tone={banner.tone} role="alert" title={banner.title}>
              <p>{banner.message}</p>
              {(banner.showHistory || banner.offerReload) && (
                <div className="alert-actions">
                  {banner.showHistory && (
                    <Link to="/history" className="button-secondary">
                      Open detection history
                    </Link>
                  )}
                  {banner.offerReload && (
                    <button
                      type="button"
                      className="button-secondary"
                      onClick={() => {
                        setBanner(null);
                        catalog.reload();
                      }}
                    >
                      <Icon name="refresh" size={15} />
                      Reload models
                    </button>
                  )}
                </div>
              )}
            </Alert>
          )}
          <div className="submit-row">
            <button
              type="submit"
              className="button-primary button-large submit-button"
              disabled={submitting || !catalogReady}
            >
              {submitting ? (
                <>
                  <Icon name="refresh" size={18} className="spin" />
                  Submitting…
                </>
              ) : (
                <>
                  Start detection
                  <Icon name="arrow" size={18} />
                </>
              )}
            </button>
            <p
              className={`submit-status ${problems > 0 && attempted && !submitting ? "has-problems" : ""}`}
              role="status"
              aria-live="polite"
            >
              {statusMessage}
            </p>
          </div>
        </section>
      </form>
    </>
  );
}

function StepHeading({
  number,
  id,
  title,
  aside,
}: {
  number: number;
  id: string;
  title: string;
  aside?: ReactNode;
}) {
  return (
    <div className="step-heading">
      <h2 id={id}>
        <span className="step-number" aria-hidden="true">
          {number}
        </span>
        <span>
          <span className="visually-hidden">Step {number}: </span>
          {title}
        </span>
      </h2>
      {aside}
    </div>
  );
}
