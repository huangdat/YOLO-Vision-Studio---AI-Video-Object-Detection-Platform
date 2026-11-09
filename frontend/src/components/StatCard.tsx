import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export function StatCard({
  label,
  value,
  icon,
  tone,
  hint,
}: {
  label: string;
  value: ReactNode;
  icon: IconName;
  tone: "blue" | "purple" | "teal" | "green" | "red";
  hint?: ReactNode;
}) {
  return (
    <article className="stat-card">
      <div className="stat-top">
        <h3>{label}</h3>
        <span className={`tile-icon ${tone}`} aria-hidden="true">
          <Icon name={icon} size={18} />
        </span>
      </div>
      <p className="stat-value">{value}</p>
      {hint && <p className="stat-hint">{hint}</p>}
    </article>
  );
}
