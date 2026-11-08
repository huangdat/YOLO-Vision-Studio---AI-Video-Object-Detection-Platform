import { useId } from "react";
import { Icon } from "../Icon";

export function VideoSourceField({
  value,
  error,
  disabled,
  onChange,
  onBlur,
}: {
  value: string;
  error?: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  onBlur: () => void;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  return (
    <div className="form-field">
      <label htmlFor={id} className="field-label">
        YouTube video URL <span className="required-mark" aria-hidden="true">*</span>
      </label>
      <div className="input-with-action">
        <input
          id={id}
          name="videoUrl"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          required
          className="text-input"
          placeholder="https://www.youtube.com/watch?v=…"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${errorId} ${hintId}` : hintId}
        />
        {value && (
          <button
            type="button"
            className="input-action"
            onClick={() => onChange("")}
            disabled={disabled}
            aria-label="Clear video URL"
          >
            <Icon name="close" size={14} />
          </button>
        )}
      </div>
      {error && (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      )}
      <p id={hintId} className="field-hint">
        A single public video: watch, youtu.be, shorts, or embed links. Playlists, other sites,
        and local files are not accepted. Only submit videos you are permitted to download and
        process; restricted or private videos will fail during download.
      </p>
    </div>
  );
}
