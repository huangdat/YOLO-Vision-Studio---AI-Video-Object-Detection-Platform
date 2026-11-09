import { useId, useState } from "react";
import { getResultJson } from "../../api/artifacts";
import { useApiResource } from "../../hooks/useApiResource";
import { Icon } from "../Icon";
import { ErrorState, LoadingSkeleton } from "../StateViews";

type CopyState = "idle" | "copied" | "failed";

/**
 * Collapsible view of the worker's original result.json (from object storage). It is shown
 * as escaped text, never as HTML, and loaded only when opened.
 */
export function ResultJsonViewer({ jobId }: { jobId: string }) {
  const [open, setOpen] = useState(false);
  const [copy, setCopy] = useState<CopyState>("idle");
  const panelId = useId();
  const json = useApiResource((signal) => getResultJson(jobId, signal), `result-json:${jobId}`, {
    enabled: open,
  });

  const copyJson = async (text: string) => {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(text);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  };

  return (
    <div className="json-result">
      <div className="media-actions">
        <button
          type="button"
          className="button-secondary"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => {
            setOpen(!open);
            setCopy("idle");
          }}
        >
          <Icon name="code" size={14} />
          {open ? "Hide JSON result" : "View JSON result"}
        </button>
      </div>
      {open && (
        <div id={panelId} className="json-panel">
          <p className="field-hint">
            The original <code>result.json</code> written by the AI worker, re-indented for
            reading; <em>Download JSON</em> keeps the original file. The statistics above come
            from the backend&apos;s result metadata, a separate representation.
          </p>
          {json.status === "loading" && <LoadingSkeleton rows={4} label="Loading result JSON" />}
          {json.status === "error" && (
            <ErrorState title="The result JSON could not be loaded" error={json.error} onRetry={json.reload} />
          )}
          {json.status === "success" && (
            <>
              <div className="json-toolbar">
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() => void copyJson(json.data.formatted)}
                >
                  <Icon name={copy === "copied" ? "check" : "layers"} size={14} />
                  {copy === "copied" ? "Copied" : "Copy JSON"}
                </button>
                <span className="json-copy-status" role="status">
                  {copy === "failed" ? "Copying is not available in this browser." : ""}
                </span>
              </div>
              <pre className="json-viewer" tabIndex={0} aria-label="Raw result JSON">
                <code>{json.data.formatted}</code>
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
