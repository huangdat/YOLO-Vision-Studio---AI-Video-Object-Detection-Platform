import { sizeName } from "../../lib/format";
import { parseConfidence, type DetectionFormState, type FormErrors } from "../../lib/detectionForm";
import type { ModelConfig } from "../../types/models";

/** Mirrors the request that will be sent. "Ready" means form-valid and enabled only. */
export function ConfigurationSummary({
  form,
  model,
  errors,
}: {
  form: DetectionFormState;
  model: ModelConfig | undefined;
  errors: FormErrors;
}) {
  const confidence = parseConfidence(form.confidence);
  const problems = Object.keys(errors).length;
  const ready = problems === 0;
  return (
    <section className="panel summary-panel" aria-labelledby="summary-title">
      <div className="section-heading">
        <div>
          <h2 id="summary-title">Detection configuration</h2>
          <p>Exactly what will be submitted.</p>
        </div>
      </div>
      <dl className="detail-list panel-body">
        <div><dt>Source</dt><dd>YouTube</dd></div>
        <div>
          <dt>Model</dt>
          <dd>{model ? `${model.version} ${sizeName(model.modelSize)}` : "—"}</dd>
        </div>
        <div><dt>Model key</dt><dd>{model ? <code>{model.modelKey}</code> : "—"}</dd></div>
        <div>
          <dt>Model status</dt>
          <dd>{model ? (model.enabled ? "Enabled" : "Disabled") : "—"}</dd>
        </div>
        <div><dt>Confidence</dt><dd>{confidence === null ? "Invalid" : confidence}</dd></div>
        <div><dt>Image size</dt><dd>{form.imageSize} px</dd></div>
        <div><dt>Classes</dt><dd>{form.classes.length} selected</dd></div>
      </dl>
      <p className={`readiness ${ready ? "ready" : "blocked"}`}>
        <span className="status-dot" aria-hidden="true" />
        {ready
          ? "Ready to submit"
          : `${problems} item${problems === 1 ? "" : "s"} to fix before submitting`}
      </p>
      <p className="field-hint">
        Ready means the configuration is valid and the model is enabled. Processing can still
        fail later, for example if the worker has not prepared the model or the video cannot be
        downloaded; such failures appear on the job page.
      </p>
    </section>
  );
}
