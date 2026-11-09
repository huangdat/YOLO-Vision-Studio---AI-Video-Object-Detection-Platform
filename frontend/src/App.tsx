import { useCallback, useRef, useState } from "react";
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

const PAGE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/detection": "Detection",
  "/history": "History",
  "/models": "Models",
};

export function App() {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const { status, refresh } = useBackendStatus();
  const location = useLocation();
  const pageTitle =
    PAGE_TITLES[location.pathname] ||
    (matchPath("/detections/:jobId", location.pathname) ? "Detection job" : "Page not found");

  const closeNavigation = useCallback(() => setNavigationOpen(false), []);
  const dismissNavigation = useCallback(() => {
    setNavigationOpen(false);
    menuButton.current?.focus();
  }, []);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <Sidebar open={navigationOpen} close={closeNavigation} dismiss={dismissNavigation} />
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <button
              ref={menuButton}
              type="button"
              className="mobile-menu icon-button"
              aria-label={navigationOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={navigationOpen}
              aria-controls="main-navigation"
              onClick={() => setNavigationOpen(!navigationOpen)}
            >
              <Icon name={navigationOpen ? "close" : "menu"} />
            </button>
            <span className="topbar-title">{pageTitle}</span>
          </div>
          <StatusBadge status={status} />
        </header>
        <main id="main-content" tabIndex={-1}>
          <Routes>
            <Route path="/" element={<Dashboard status={status} refresh={refresh} />} />
            <Route path="/detection" element={<Detection />} />
            <Route path="/history" element={<History />} />
            <Route path="/detections/:jobId" element={<DetectionDetails />} />
            <Route path="/models" element={<Models />} />
            <Route
              path="*"
              element={
                <section className="card placeholder-panel">
                  <h1>Page not found</h1>
                  <p>This page does not exist.</p>
                  <Link to="/" className="button-primary">
                    Back to dashboard
                    <Icon name="arrow" size={17} />
                  </Link>
                </section>
              }
            />
          </Routes>
        </main>
      </div>
    </div>
  );
}
