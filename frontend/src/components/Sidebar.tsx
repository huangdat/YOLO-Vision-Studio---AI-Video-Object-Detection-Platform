import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Icon, type IconName } from "./Icon";

/** Matches the stylesheet breakpoint below which the sidebar becomes a drawer. */
const DRAWER_QUERY = "(max-width: 1023px)";

function useDrawerLayout(): boolean {
  const [drawer, setDrawer] = useState(() => window.matchMedia?.(DRAWER_QUERY).matches ?? false);
  useEffect(() => {
    const query = window.matchMedia?.(DRAWER_QUERY);
    if (!query) return;
    const update = () => setDrawer(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return drawer;
}

const navigation: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Dashboard", icon: "dashboard" },
  { to: "/detection", label: "Detection", icon: "scan" },
  { to: "/history", label: "History", icon: "history" },
  { to: "/models", label: "Models", icon: "models" },
];

/**
 * Persistent sidebar on wide screens; an off-canvas drawer on small screens. While the
 * drawer is open, Escape closes it and focus starts on the first link.
 */
export function Sidebar({
  open,
  close,
  dismiss,
}: {
  open: boolean;
  /** Close after following a link (focus moves with the navigation). */
  close: () => void;
  /** Close without navigating (Escape, overlay, close button); focus returns to the menu button. */
  dismiss: () => void;
}) {
  const onJobPage = useLocation().pathname.startsWith("/detections/");
  const firstLink = useRef<HTMLAnchorElement>(null);
  const drawer = useDrawerLayout();

  useEffect(() => {
    if (!open) return;
    // One frame later, so the drawer is no longer inert when focus moves into it.
    const frame = window.requestAnimationFrame(() => firstLink.current?.focus());
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, dismiss]);

  return (
    <>
      {open && (
        <button
          type="button"
          className="sidebar-overlay"
          aria-label="Close navigation"
          tabIndex={-1}
          onClick={dismiss}
        />
      )}
      <aside
        id="main-navigation"
        className={`sidebar ${open ? "open" : ""}`}
        aria-label="Main navigation"
        // A closed drawer is off-screen: inert keeps it out of the tab order and the
        // accessibility tree. The desktop sidebar is never inert.
        inert={drawer && !open}
      >
        <div className="sidebar-top">
          <NavLink
            to="/"
            className="brand"
            onClick={close}
            aria-label="YOLO Vision Studio home"
            ref={firstLink}
          >
            <span className="brand-mark" aria-hidden="true">
              <Icon name="vision" size={20} />
            </span>
            <span className="brand-name">
              YOLO Vision <span>Studio</span>
            </span>
          </NavLink>
          <button
            type="button"
            className="icon-button sidebar-close"
            aria-label="Close navigation"
            onClick={dismiss}
          >
            <Icon name="close" size={18} />
          </button>
        </div>
        <nav>
          <ul className="nav-list">
            {navigation.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  onClick={close}
                  className={({ isActive }) =>
                    `nav-link ${isActive || (item.to === "/history" && onJobPage) ? "active" : ""}`
                  }
                >
                  <Icon name={item.icon} size={19} />
                  <span>{item.label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <p className="sidebar-footer">YOLO Vision Studio · v1.0.0</p>
      </aside>
    </>
  );
}
