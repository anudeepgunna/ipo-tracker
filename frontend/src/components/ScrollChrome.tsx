import { useScrollProgress, useScrolledPast } from "../lib/motion";

/**
 * A hairline bar showing how far down the page you are.
 *
 * Driven by a CSS transform rather than a width change, so it stays on the
 * compositor and never triggers layout while scrolling.
 */
export function ScrollProgress() {
  const progress = useScrollProgress();
  return (
    <div className="scroll-progress" aria-hidden="true">
      <div className="scroll-progress-bar" style={{ transform: `scaleX(${progress})` }} />
    </div>
  );
}

export function BackToTop() {
  const visible = useScrolledPast(420);

  return (
    <button
      className={`back-to-top${visible ? " visible" : ""}`}
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
      aria-label="Back to top"
      // Hidden from the tab order while invisible, so keyboard users don't land
      // on a control they cannot see.
      tabIndex={visible ? 0 : -1}
    >
      ↑
    </button>
  );
}
