import type { ReactNode } from "react";
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
        <Icon name={icon} size={24} />
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
        <Icon name="alert" size={24} />
      </span>
      <h3>{title}</h3>
      <p className="state-body">{error.message}</p>
      {onRetry && error.retryable && (
        <button type="button" className="button-secondary" onClick={onRetry}>
          <Icon name="refresh" size={14} />
          Try again
        </button>
      )}
    </div>
  );
}
