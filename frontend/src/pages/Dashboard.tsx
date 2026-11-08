import { Link } from "react-router-dom";
import { Icon } from "../components/Icon";
import { StatusBadge } from "../components/StatusBadge";
import type { BackendStatus } from "../hooks/useBackendStatus";

export function Dashboard({
  status,
  refresh,
}: {
  status: BackendStatus;
  refresh: () => Promise<void>;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR VISION WORKSPACE</p>
          <h1>
            YOLO Vision Studio<span className="title-dot">.</span>
          </h1>
          <p className="page-description">
            AI-Powered Video Object Detection Platform
          </p>
        </div>
        <span className="phase-pill">
          <span />
          Phase 01 · Foundation
        </span>
      </div>

      <section className="hero-panel" aria-labelledby="hero-title">
        <div className="hero-copy">
          <span className="hero-kicker">
            <Icon name="vision" size={15} />
            BUILT FOR WHAT COMES NEXT
          </span>
          <h2 id="hero-title">
            Turn video into
            <br />
            <span>meaningful insight.</span>
          </h2>
          <p>
            A dedicated workspace for intelligent object detection. Your
            platform foundation is here. Video analysis is coming in a future
            phase.
          </p>
          <Link to="/detection" className="button-primary">
            Explore the workspace
            <Icon name="arrow" size={17} />
          </Link>
          <div className="hero-footnote">
            <span />
            Modular by design. Ready to evolve.
          </div>
        </div>
        <div className="vision-art" aria-hidden="true">
          <div className="art-orbit orbit-one" />
          <div className="art-orbit orbit-two" />
          <div className="art-grid" />
          <div className="art-corner top-left" />
          <div className="art-corner top-right" />
          <div className="art-corner bottom-left" />
          <div className="art-corner bottom-right" />
          <div className="vision-core">
            <Icon name="vision" size={80} />
          </div>
          <div className="art-node node-a">
            <Icon name="scan" size={20} />
          </div>
          <div className="art-node node-b">
            <Icon name="cpu" size={20} />
          </div>
          <div className="art-node node-c">
            <Icon name="layers" size={20} />
          </div>
          <div className="art-caption">
            <span />
            VISION ENGINE<span className="art-caption-divider">/</span>COMING
            SOON
          </div>
        </div>
      </section>

      <section className="summary-grid" aria-label="Platform overview">
        <article className="summary-card">
          <div className="summary-top">
            <span className="tile-icon blue">
              <Icon name="server" />
            </span>
            <span className="card-label">LIVE CONNECTION</span>
          </div>
          <h3>Backend API</h3>
          <StatusBadge status={status} />
          <p>
            {status.state === "connected"
              ? `Spring Boot · v${status.info.version}`
              : status.state === "checking"
                ? "Contacting the system information endpoint…"
                : "The backend is currently unreachable."}
          </p>
        </article>
        <article className="summary-card">
          <div className="summary-top">
            <span className="tile-icon purple">
              <Icon name="layers" />
            </span>
            <span className="card-label">CURRENT MILESTONE</span>
          </div>
          <h3>Platform foundation</h3>
          <div className="summary-value">
            Phase <span>01</span>
          </div>
          <p>Independent services. One connected workspace.</p>
        </article>
        <article className="summary-card">
          <div className="summary-top">
            <span className="tile-icon teal">
              <Icon name="cpu" />
            </span>
            <span className="card-label">DEFAULT CONFIGURATION</span>
          </div>
          <h3>CPU compatible</h3>
          <div className="summary-value">No GPU required</div>
          <p>Lightweight startup. No model downloads.</p>
        </article>
      </section>

      <section className="connection-panel" aria-labelledby="connection-title">
        <div className="section-heading">
          <div>
            <h2 id="connection-title">System connection</h2>
            <p>Live status from your backend, refreshed every 30 seconds.</p>
          </div>
          <button
            className="button-secondary"
            onClick={() => {
              void refresh();
            }}
            disabled={status.state === "checking"}
          >
            <Icon
              name="refresh"
              size={16}
              className={status.state === "checking" ? "spin" : ""}
            />
            Refresh
          </button>
        </div>
        <div className="connection-content">
          <div className="endpoint">
            <span className="method-label">GET</span>
            <code>/api/v1/system/info</code>
          </div>
          {status.state === "connected" ? (
            <div className="connection-success">
              <span>
                <Icon name="check" size={16} />
                {status.info.application}
              </span>
              <span>
                Last checked{" "}
                {status.checkedAt.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
          ) : status.state === "disconnected" ? (
            <p className="connection-error" role="alert">
              {status.message}
            </p>
          ) : (
            <p className="connection-pending">
              Checking the backend connection…
            </p>
          )}
        </div>
      </section>

      <section className="coming-section" aria-labelledby="coming-title">
        <div className="section-heading">
          <div>
            <h2 id="coming-title">The road ahead</h2>
            <p>A clear path from foundation to intelligent video analysis.</p>
          </div>
          <span className="subtle-label">FUTURE CAPABILITIES</span>
        </div>
        <div className="roadmap-grid">
          {[
            {
              title: "Video detection",
              description: "Configure a model and analyze video with YOLO.",
              icon: "scan" as const,
              link: "/detection",
              number: "01",
            },
            {
              title: "Detection history",
              description: "Revisit processed videos and their results.",
              icon: "history" as const,
              link: "/history",
              number: "02",
            },
            {
              title: "Model workspace",
              description:
                "Explore model versions and sizes for your use case.",
              icon: "models" as const,
              link: "/models",
              number: "03",
            },
          ].map((item) => (
            <Link className="roadmap-card" to={item.link} key={item.title}>
              <div className="roadmap-top">
                <Icon name={item.icon} size={22} />
                <span>{item.number}</span>
              </div>
              <h3>
                {item.title}
                <Icon name="arrow" size={16} />
              </h3>
              <p>{item.description}</p>
              <span className="coming-label">Coming in a future phase</span>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
