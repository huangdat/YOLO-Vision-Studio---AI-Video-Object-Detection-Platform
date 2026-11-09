import type { BackendStatus } from "../hooks/useBackendStatus";

/** Backend connection state as a short text label plus a coloured dot. */
export function StatusBadge({ status }: { status: BackendStatus }) {
  const labels = {
    checking: "Checking connection",
    connected: "Connected",
    disconnected: "Backend unavailable",
  };
  return (
    <span className={`status-badge ${status.state}`} role="status">
      <span className="status-dot" aria-hidden="true" />
      {labels[status.state]}
    </span>
  );
}
