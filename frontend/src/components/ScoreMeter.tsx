import type { Score } from "../lib/types";

function colorFor(score: number): string {
  if (score >= 65) return "var(--good)";
  if (score >= 40) return "var(--warn)";
  return "var(--bad)";
}

/**
 * The outlook score, always rendered with its confidence.
 *
 * A bare number invites more trust than this heuristic deserves, so the meter
 * never appears without either a confidence figure or an explicit "not enough
 * data yet".
 */
export function ScoreMeter({ score, showLabel = true }: { score: Score | null; showLabel?: boolean }) {
  if (!score || score.score === null) {
    return <div className="muted">Not enough data yet</div>;
  }

  return (
    <div>
      {showLabel && <div className="stat-label">Listing outlook</div>}
      <div className="score-row">
        <div className="meter">
          <div
            className="meter-fill"
            style={{ width: `${score.score}%`, background: colorFor(score.score) }}
          />
        </div>
        <span className="score-num" style={{ color: colorFor(score.score) }}>
          {score.score}
        </span>
      </div>
      <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
        {Math.round(score.confidence * 100)}% confidence
      </div>
    </div>
  );
}

/** Full breakdown: every component, its weight, and what it contributed. */
export function ScoreBreakdown({ score }: { score: Score | null }) {
  if (!score || score.score === null) {
    return (
      <div className="card">
        <h2>Listing outlook</h2>
        <p className="muted">
          {score?.notes?.[0] ?? "Not enough data yet to compute an outlook."}
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Listing outlook — how this is calculated</h2>
      <div className="score-row" style={{ marginBottom: 16 }}>
        <div className="meter" style={{ height: 10 }}>
          <div
            className="meter-fill"
            style={{ width: `${score.score}%`, background: colorFor(score.score) }}
          />
        </div>
        <span className="score-num" style={{ fontSize: 22, color: colorFor(score.score) }}>
          {score.score}
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Signal</th>
              <th>Reading</th>
              <th className="num">Component</th>
              <th className="num">Weight</th>
            </tr>
          </thead>
          <tbody>
            {score.components.map((c) => (
              <tr key={c.key}>
                <td>{c.label}</td>
                <td className="muted">{c.detail}</td>
                <td className="num">{Math.round(c.score)}</td>
                <td className="num">{Math.round(c.weight * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {score.notes.length > 0 && (
        <ul className="muted" style={{ marginTop: 12, paddingLeft: 18 }}>
          {score.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
