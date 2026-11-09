import { useEffect, useId, useState, type ReactNode } from "react";
import type { ApiError } from "../api/client";
import { Icon, type IconName } from "./Icon";

/** Shimmering placeholder rows; a hidden status message is announced instead. */
export function LoadingSkeleton({ rows = 3, label }: { rows?: number; label: string }) {
  return (
    <div className="skeleton-group" role="status" aria-live="polite">
      <span className="visually-hidden">{label}</span>
      {Array.from({ length: rows }, (_, index) => (
        <span key={index} className="skeleton-line" aria-hidden="true" />
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
}: {
  icon: IconName;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="state-panel">
      <span className="state-icon">
        <Icon name={icon} size={22} />
      </span>
      <h3>{title}</h3>
      {children && <div className="state-body">{children}</div>}
    </div>
  );
}

/** API failure with the normalised message and, where useful, a retry action. */
export function ErrorState({
  error,
  title = "Something went wrong",
  onRetry,
}: {
  error: ApiError;
  title?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state-panel error" role="alert">
      <span className="state-icon">
        <Icon name="alert" size={22} />
      </span>
      <h3>{title}</h3>
      <p className="state-body">{error.message}</p>
      {onRetry && error.retryable && (
        <button type="button" className="button-secondary" onClick={onRetry}>
          <Icon name="refresh" size={15} />
          Try again
        </button>
      )}
    </div>
  );
}

export type AlertTone = "info" | "success" | "warning" | "error";

const ALERT_ICON: Record<AlertTone, IconName> = {
  info: "alert",
  success: "check",
  warning: "alert",
  error: "alert",
};

/** Inline message with a tone, a short title, and optional body and actions. */
export function Alert({
  tone,
  title,
  children,
  role,
}: {
  tone: AlertTone;
  title?: ReactNode;
  children?: ReactNode;
  role?: "alert" | "status";
}) {
  return (
    <div className={`alert alert-${tone}`} role={role}>
      <span className="alert-icon">
        <Icon name={ALERT_ICON[tone]} size={18} />
      </span>
      <div className="alert-content">
        {title && <strong className="alert-title">{title}</strong>}
        {children}
      </div>
    </div>
  );
}

/**
 * Button-controlled disclosure for secondary content. Content is rendered only while
 * open, so hidden sections never load data or trap focus.
 */
export function Disclosure({
  label,
  summary,
  defaultOpen = false,
  forceOpen = false,
  children,
  className = "",
}: {
  label: string;
  summary?: ReactNode;
  defaultOpen?: boolean;
  /** Keeps the section open, for example while it contains a validation error. */
  forceOpen?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const [userOpen, setUserOpen] = useState(defaultOpen);
  const open = userOpen || forceOpen;
  const panelId = useId();
  // Once forced open (for example by a validation error), stay open after the error is
  // fixed, so the section never collapses while the user is still editing it.
  useEffect(() => {
    if (forceOpen) setUserOpen(true);
  }, [forceOpen]);
  return (
    <div className={`disclosure ${open ? "open" : ""} ${className}`}>
      <button
        type="button"
        className="disclosure-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setUserOpen(forceOpen ? true : !open)}
      >
        <span className="disclosure-label">
          <span>{label}</span>
          {summary && !open && <span className="disclosure-summary">{summary}</span>}
        </span>
        <Icon name="chevronDown" size={18} className="disclosure-chevron" />
      </button>
      {open && (
        <div id={panelId} className="disclosure-panel">
          {children}
        </div>
      )}
    </div>
  );
}
