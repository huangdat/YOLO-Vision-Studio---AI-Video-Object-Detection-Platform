import type { ReactNode } from "react";

/** One page title per route, with optional supporting text and actions. */
export function PageHeader({
  eyebrow,
  title,
  description,
  aside,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div className="page-heading-text">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {aside && <div className="page-heading-actions">{aside}</div>}
    </div>
  );
}
