import type { CSSProperties } from "react";

export type IconName =
  | "vision"
  | "dashboard"
  | "scan"
  | "history"
  | "models"
  | "arrow"
  | "server"
  | "layers"
  | "cpu"
  | "refresh"
  | "menu"
  | "close"
  | "code"
  | "check"
  | "external"
  | "alert"
  | "chevronLeft"
  | "chevronRight"
  | "activity"
  | "film"
  | "download"
  | "chevronDown"
  | "play"
  | "link"
  | "sliders"
  | "camera";

const paths: Record<IconName, React.ReactNode> = {
  vision: (
    <>
      <path d="M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5" />
      <circle cx="12" cy="12" r="4" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  scan: (
    <>
      <path d="M7 3H3v4m14-4h4v4m0 10v4h-4M7 21H3v-4M3 12h18" />
      <rect x="7" y="7" width="10" height="10" rx="2" />
    </>
  ),
  history: (
    <>
      <path d="M3 11a9 9 0 1 1 2.3 7M3 4v7h7m2-4v5l3 2" />
    </>
  ),
  models: (
    <>
      <path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" />
    </>
  ),
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  server: (
    <>
      <rect x="3" y="3" width="18" height="7" rx="2" />
      <rect x="3" y="14" width="18" height="7" rx="2" />
      <path d="M7 6.5h.01M7 17.5h.01m4-11h6m-6 11h6" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" />
    </>
  ),
  cpu: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M9 1v5m6-5v5m-6 12v5m6-5v5M1 9h5m-5 6h5m12-6h5m-5 6h5" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
    </>
  ),
  refresh: (
    <path d="M20 7v5h-5M4 17v-5h5m10.2-4A8 8 0 0 0 5.4 6M4.8 16a8 8 0 0 0 13.8 2" />
  ),
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  code: <path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18" />,
  check: <path d="m5 12 4 4L19 6" />,
  external: (
    <path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" />
  ),
  alert: (
    <>
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9v4m0 4h.01" />
    </>
  ),
  chevronLeft: <path d="m15 18-6-6 6-6" />,
  chevronDown: <path d="m6 9 6 6 6-6" />,
  play: <path d="M8 5.5v13l10-6.5-10-6.5Z" />,
  link: <path d="M10 14a4 4 0 0 0 5.7 0l3.6-3.6a4 4 0 0 0-5.7-5.7L12 6.3m2 3.7a4 4 0 0 0-5.7 0l-3.6 3.6a4 4 0 0 0 5.7 5.7l1.6-1.6" />,
  sliders: <path d="M4 6h10m4 0h2M4 12h4m4 0h8M4 18h12m4 0h0M14 4v4M8 10v4m8 2v4" />,
  camera: (
    <>
      <path d="M15 10.5 20 7v10l-5-3.5" />
      <rect x="3" y="6" width="12" height="12" rx="2" />
    </>
  ),
  chevronRight: <path d="m9 18 6-6-6-6" />,
  activity: <path d="M22 12h-4l-3 9L9 3l-3 9H2" />,
  download: <path d="M12 4v11m-5-5 5 5 5-5M5 20h14" />,
  film: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M7 3v18M17 3v18M3 7.5h4m10 0h4M3 12h18M3 16.5h4m10 0h4" />
    </>
  ),
};

export function Icon({
  name,
  size = 20,
  style,
  className = "",
}: {
  name: IconName;
  size?: number;
  style?: CSSProperties;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
      style={style}
    >
      {paths[name]}
    </svg>
  );
}
