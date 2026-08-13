import { useEffect, useState } from "react";

import { useReducedMotion } from "../lib/motion";
import type { Score } from "../lib/types";

function colorFor(score: number): string {
  if (score >= 65) return "var(--good)";
  if (score >= 40) return "var(--warn)";
  return "var(--bad)";
}

/**
 * Circular gauge for the listing-outlook score.
 *
 * The arc is drawn with stroke-dashoffset so it sweeps into place. The track
 * behind it stays visible at low scores, which a bare arc would not — 8/100
 * should still read as "a measured value near the bottom", not "nearly nothing
 * rendered".
 */
export function ScoreRing({
  score,
  size = 62,
  stroke = 6,
  showConfidence = true,
}: {
  score: Score | null;
  size?: number;
  stroke?: number;
  showConfidence?: boolean;
}) {
  const reduced = useReducedMotion();
  const value = score?.score ?? null;
  const [drawn, setDrawn] = useState(reduced ? (value ?? 0) : 0);

  useEffect(() => {
    if (value === null) return;
    if (reduced) {
      setDrawn(value);
      return;
    }
    // Next frame, so the browser paints at 0 first and the transition runs.
    const id = requestAnimationFrame(() => setDrawn(value));
    return () => cancelAnimationFrame(id);
  }, [value, reduced]);

  if (value === null) {
    return (
      <div className="score-empty">
        <span className="muted" style={{ fontSize: 12 }}>
          Not enough data yet
        </span>
      </div>
    );
  }

  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - drawn / 100);
  const color = colorFor(value);

  return (
    <div className="score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--surface-2)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          // Start the sweep at 12 o'clock rather than 3.
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{
            transition: reduced ? "none" : "stroke-dashoffset 1.1s cubic-bezier(.22,1,.36,1)",
          }}
        />
      </svg>
      <div className="score-ring-label">
        <span style={{ color, fontSize: size / 3.4 }}>{Math.round(drawn)}</span>
        {showConfidence && score && (
          <span className="muted" style={{ fontSize: 9 }}>
            {Math.round(score.confidence * 100)}%
          </span>
        )}
      </div>
      <span className="sr-only">
        Listing outlook {value} out of 100, {Math.round((score?.confidence ?? 0) * 100)}% confidence
      </span>
    </div>
  );
}
