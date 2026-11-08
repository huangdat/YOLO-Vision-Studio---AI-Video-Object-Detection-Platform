import type { BackendStatus } from "../hooks/useBackendStatus";

export function StatusBadge({ status }: { status: BackendStatus }) {
  const labels = {
    checking: "Checking backend",
    connected: "Backend connected",
    disconnected: "Backend offline",
  };
  return (
    <span className={`status-badge ${status.state}`} role="status">
      <span className="status-dot" />
      {labels[status.state]}
    </span>
  );
}
