import { useState } from "react";
import { Link, matchPath, Route, Routes, useLocation } from "react-router-dom";
import { Icon } from "./components/Icon";
import { Sidebar } from "./components/Sidebar";
import { StatusBadge } from "./components/StatusBadge";
import { useBackendStatus } from "./hooks/useBackendStatus";
import { Dashboard } from "./pages/Dashboard";
import { Detection } from "./pages/Detection";
import { DetectionDetails } from "./pages/DetectionDetails";
import { History } from "./pages/History";
import { Models } from "./pages/Models";

export function App() {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const { status, refresh } = useBackendStatus();
  const location = useLocation();
  const pageTitle =
    (
      {
        "/": "Dashboard",
        "/detection": "Detection",
        "/history": "History",
        "/models": "Models",
      } as Record<string, string>
    )[location.pathname] ||
    (matchPath("/detections/:jobId", location.pathname)
      ? "Detection job"
      : "Page not found");

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <Sidebar open={navigationOpen} close={() => setNavigationOpen(false)} />
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="mobile-menu icon-button"
              aria-label={
                navigationOpen ? "Close navigation" : "Open navigation"
              }
              aria-expanded={navigationOpen}
              onClick={() => setNavigationOpen(!navigationOpen)}
            >
              <Icon name={navigationOpen ? "close" : "menu"} />
            </button>
            <span className="breadcrumb-root">Workspace</span>
            <span className="breadcrumb-slash">/</span>
            <span>{pageTitle}</span>
          </div>
          <div className="topbar-right">
            <StatusBadge status={status} />
            <span
              className="workspace-avatar"
              aria-label="Vision Studio workspace"
            >
              VS
            </span>
          </div>
        </header>
        <main id="main-content">
          <Routes>
            <Route
              path="/"
              element={<Dashboard status={status} refresh={refresh} />}
            />
            <Route path="/detection" element={<Detection />} />
            <Route path="/history" element={<History />} />
            <Route path="/detections/:jobId" element={<DetectionDetails />} />
            <Route path="/models" element={<Models />} />
            <Route
              path="*"
              element={
                <section className="placeholder-panel">
                  <h1>Page not found</h1>
                  <p>This page does not exist in your workspace.</p>
                  <Link to="/" className="button-primary">
                    Back to dashboard
                    <Icon name="arrow" size={17} />
                  </Link>
                </section>
              }
            />
          </Routes>
          <footer className="page-footer">
            <span>YOLO Vision Studio</span>
            <span>Built for a clearer view.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
