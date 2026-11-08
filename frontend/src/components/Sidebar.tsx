import { NavLink, useLocation } from "react-router-dom";
import { Icon, type IconName } from "./Icon";

const navigation: {
  to: string;
  label: string;
  icon: IconName;
  soon?: boolean;
}[] = [
  { to: "/", label: "Dashboard", icon: "dashboard" },
  { to: "/detection", label: "Detection", icon: "scan", soon: true },
  { to: "/history", label: "History", icon: "history" },
  { to: "/models", label: "Models", icon: "models" },
];

export function Sidebar({ open, close }: { open: boolean; close: () => void }) {
  const onJobPage = useLocation().pathname.startsWith("/detections/");
  return (
    <>
      {open && (
        <button
          className="sidebar-overlay"
          aria-label="Close navigation"
          onClick={close}
        />
      )}
      <aside
        className={`sidebar ${open ? "open" : ""}`}
        aria-label="Main navigation"
      >
        <NavLink
          to="/"
          className="brand"
          onClick={close}
          aria-label="YOLO Vision Studio home"
        >
          <span className="brand-mark">
            <Icon name="vision" size={27} />
          </span>
          <span>
            <strong>
              YOLO <span>Vision</span>
            </strong>
            <small>STUDIO</small>
          </span>
        </NavLink>
        <div className="workspace-label">WORKSPACE</div>
        <nav>
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={close}
              className={({ isActive }) =>
                `nav-link ${isActive || (item.to === "/history" && onJobPage) ? "active" : ""}`
              }
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.soon && <span className="nav-soon">Soon</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="phase-card">
            <span className="phase-card-icon">
              <Icon name="code" />
            </span>
            <div>
              <strong>Dashboard &amp; API integration</strong>
              <p>Phase 07 · Live job data</p>
            </div>
            <div className="phase-progress">
              <span />
            </div>
          </div>
          <div className="sidebar-footer">
            <span className="version-dot" />
            YOLO Vision Studio<span>v1.0.0</span>
          </div>
        </div>
      </aside>
    </>
  );
}
