import { Link } from "react-router-dom";

import { formatMoney, formatTimes } from "../lib/api";
import type { Ipo } from "../lib/types";
import { ScoreMeter } from "./ScoreMeter";

function closingLabel(ipo: Ipo): string | null {
  if (ipo.status !== "OPEN" || ipo.days_to_close === null) return null;
  if (ipo.days_to_close === 0) return "LAST DAY";
  if (ipo.days_to_close === 1) return "1 day left";
  if (ipo.days_to_close > 1) return `${ipo.days_to_close} days left`;
  return null;
}

export function IpoCard({
  ipo,
  onToggleWatch,
  signedIn,
}: {
  ipo: Ipo;
  onToggleWatch?: (ipo: Ipo) => void;
  signedIn: boolean;
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
    <div className={`ipo-card${ipo.is_last_day ? " last-day" : ""}`}>
      <div className="ipo-head">
        <div>
          <Link to={`/ipo/${ipo.symbol}`} className="ipo-name">
            {ipo.company_name}
          </Link>
          <div className="ipo-symbol">{ipo.symbol}</div>
        </div>
        {signedIn && onToggleWatch && (
          <button
            className="btn secondary small"
            onClick={() => onToggleWatch(ipo)}
            title={ipo.watchlisted ? "Remove from watchlist" : "Add to watchlist"}
            aria-label={ipo.watchlisted ? "Remove from watchlist" : "Add to watchlist"}
          >
            {ipo.watchlisted ? "★" : "☆"}
          </button>
        )}
      </div>

      <div className="badges">
        <span className={`badge ${ipo.status.toLowerCase()}`}>{ipo.status}</span>
        {ipo.board === "SME" && <span className="badge sme">SME</span>}
        {closing && (
          <span className={`badge ${ipo.is_last_day ? "last-day" : "upcoming"}`}>{closing}</span>
        )}
      </div>

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
          <div className="stat-value">{formatTimes(total)}</div>
        </div>
        <div>
          <div className="stat-label">GMP</div>
          <div
            className={`stat-value${gain === null ? "" : gain >= 0 ? " good" : " bad"}`}
          >
            {ipo.gmp?.gmp_value != null
              ? `${formatMoney(ipo.gmp.gmp_value)}${gain !== null ? ` (${gain >= 0 ? "+" : ""}${gain.toFixed(1)}%)` : ""}`
              : "—"}
          </div>
        </div>
      </div>

      <ScoreMeter score={ipo.score} />
    </div>
  );
}
