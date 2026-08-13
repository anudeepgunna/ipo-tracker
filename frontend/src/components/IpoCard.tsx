import { Link } from "react-router-dom";

import { formatMoney } from "../lib/api";
import { useCountUp } from "../lib/motion";
import type { Ipo } from "../lib/types";
import { Countdown } from "./Countdown";
import { ScoreRing } from "./ScoreRing";

function closingLabel(ipo: Ipo): string | null {
  if (ipo.status !== "OPEN" || ipo.days_to_close === null) return null;
  if (ipo.days_to_close === 0) return "LAST DAY";
  if (ipo.days_to_close === 1) return "1 day left";
  if (ipo.days_to_close > 1) return `${ipo.days_to_close} days left`;
  return null;
}

/** Subscription multiple, counting up on arrival. */
function Subscription({ value }: { value: number | null }) {
  const shown = useCountUp(value);
  if (shown === null) return <span className="stat-value">—</span>;

  // Heavy oversubscription is the signal worth spotting at a glance.
  const hot = (value ?? 0) >= 10;
  return (
    <span className={`stat-value${hot ? " hot" : ""}`}>
      {shown.toFixed(2)}x{hot && <span className="flame">🔥</span>}
    </span>
  );
}

export function IpoCard({
  ipo,
  onToggleWatch,
  onRemind,
  reminderCount = 0,
  signedIn,
  index = 0,
}: {
  ipo: Ipo;
  onToggleWatch?: (ipo: Ipo) => void;
  onRemind?: (ipo: Ipo) => void;
  reminderCount?: number;
  signedIn: boolean;
  index?: number;
}) {
  const total = ipo.subscription?.TOTAL ?? null;
  const closing = closingLabel(ipo);
  const gain = ipo.expected_gain_pct;

  const band =
    ipo.price_band_min && ipo.price_band_max
      ? ipo.price_band_min === ipo.price_band_max
        ? formatMoney(ipo.price_band_max)
        : `${formatMoney(ipo.price_band_min)}–${formatMoney(ipo.price_band_max)}`
      : "—";

  return (
    <article
      className={`ipo-card reveal${ipo.is_last_day ? " last-day" : ""}`}
      // Stagger the entrance so the grid assembles rather than snapping in.
      // Capped so a long list never leaves the last card waiting.
      style={{ animationDelay: `${Math.min(index, 11) * 45}ms` }}
    >
      <div className="ipo-head">
        <div style={{ minWidth: 0 }}>
          <Link to={`/ipo/${ipo.symbol}`} className="ipo-name">
            {ipo.company_name}
          </Link>
          <div className="ipo-symbol">{ipo.symbol}</div>
        </div>
        <div className="card-actions">
          {signedIn && onToggleWatch && (
            <button
              className={`icon-toggle${ipo.watchlisted ? " on" : ""}`}
              onClick={() => onToggleWatch(ipo)}
              title={ipo.watchlisted ? "Remove from watchlist" : "Add to watchlist"}
              aria-label={ipo.watchlisted ? "Remove from watchlist" : "Add to watchlist"}
            >
              {ipo.watchlisted ? "★" : "☆"}
            </button>
          )}
          {/* Shown signed-out too: the reminder is the reason to make an account,
              so gating it behind login loses people before they see the value. */}
          {onRemind && ipo.status !== "LISTED" && ipo.status !== "CLOSED" && (
            <button
              className={`bell${reminderCount > 0 ? " on" : ""}`}
              onClick={() => onRemind(ipo)}
              title={
                reminderCount > 0
                  ? `${reminderCount} reminder${reminderCount > 1 ? "s" : ""} set`
                  : "Remind me about this IPO"
              }
            >
              <span className="bell-icon">🔔</span>
              {reminderCount > 0 ? reminderCount : "Remind me"}
            </button>
          )}
        </div>
      </div>

      <div className="badges">
        <span className={`badge ${ipo.status.toLowerCase()}`}>
          {ipo.status === "OPEN" && <span className="live-dot" />}
          {ipo.status}
        </span>
        {ipo.board === "SME" && <span className="badge sme">SME</span>}
        {closing && (
          <span className={`badge ${ipo.is_last_day ? "last-day" : "upcoming"}`}>{closing}</span>
        )}
      </div>

      {ipo.is_last_day && <Countdown closeDate={ipo.close_date} compact />}

      <div className="stats">
        <div>
          <div className="stat-label">Price band</div>
          <div className="stat-value">{band}</div>
        </div>
        <div>
          <div className="stat-label">Min investment</div>
          <div className="stat-value">{formatMoney(ipo.min_investment)}</div>
        </div>
        <div>
          <div className="stat-label">Subscribed</div>
          <Subscription value={total} />
        </div>
        <div>
          <div className="stat-label">GMP</div>
          <div className={`stat-value${gain === null ? "" : gain >= 0 ? " good" : " bad"}`}>
            {ipo.gmp?.gmp_value != null
              ? `${formatMoney(ipo.gmp.gmp_value)}${
                  gain !== null ? ` (${gain >= 0 ? "+" : ""}${gain.toFixed(1)}%)` : ""
                }`
              : "—"}
          </div>
        </div>
      </div>

      <div className="card-footer">
        <ScoreRing score={ipo.score} />
        <div style={{ minWidth: 0 }}>
          <div className="stat-label">Listing outlook</div>
          <div className="muted" style={{ fontSize: 12 }}>
            {ipo.score?.score === null || !ipo.score
              ? "Waiting for bids"
              : ipo.estimated_listing_price
                ? `Est. listing ${formatMoney(ipo.estimated_listing_price)}`
                : "Based on subscription only"}
          </div>
        </div>
      </div>
    </article>
  );
}
