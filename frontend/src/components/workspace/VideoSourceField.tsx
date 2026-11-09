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
          className="text-input input-large"
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
            <Icon name="close" size={16} />
          </button>
        )}
      </div>
      {error && (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      )}
      <p id={hintId} className="field-hint">
        Paste a public YouTube video link that you are allowed to process. Single videos only
        (watch, youtu.be, Shorts, or embed links); playlists are not supported.
      </p>
    </div>
  );
}
