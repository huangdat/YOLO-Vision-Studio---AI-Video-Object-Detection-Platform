import { Link } from "react-router-dom";
import { Icon, type IconName } from "../components/Icon";

export function Placeholder({
  title,
  description,
  icon,
}: {
  title: string;
  description: string;
  icon: IconName;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR VISION WORKSPACE</p>
          <h1>{title}</h1>
          <p className="page-description">{description}</p>
        </div>
        <span className="phase-pill">Future capability</span>
      </div>
      <section className="placeholder-panel">
        <span className="placeholder-icon">
          <Icon name={icon} size={42} />
        </span>
        <span className="hero-kicker">COMING IN A FUTURE PHASE</span>
        <h2>A little further on the roadmap.</h2>
        <p>
          This workspace is reserved for {title.toLowerCase()}. Phase 1
          establishes the platform and service connections; this feature is not
          available yet.
        </p>
        <Link to="/" className="button-primary">
          Back to dashboard
          <Icon name="arrow" size={17} />
        </Link>
      </section>
    </>
  );
}
