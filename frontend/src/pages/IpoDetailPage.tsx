import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { Countdown } from "../components/Countdown";
import { ScoreBreakdown } from "../components/ScoreMeter";
import { ScoreRing } from "../components/ScoreRing";
import { SubscriptionChart } from "../components/SubscriptionChart";
import { api, formatDate, formatMoney, formatTimes } from "../lib/api";

const CATEGORY_LABELS: Record<string, string> = {
  QIB: "Qualified institutional (QIB)",
  NII: "Non-institutional (NII)",
  RETAIL: "Retail (RII)",
  EMPLOYEE: "Employees",
  OTHER: "Other",
  TOTAL: "Total",
};

const ORDER = ["QIB", "NII", "RETAIL", "EMPLOYEE", "OTHER", "TOTAL"];

export function IpoDetailPage() {
  const { symbol = "" } = useParams();
  const { data: ipo, isLoading, error } = useQuery({
    queryKey: ["ipo", symbol],
    queryFn: () => api.getIpo(symbol),
  });

  if (isLoading) return <div className="container empty">Loading…</div>;
  if (error) return <div className="container empty">{(error as Error).message}</div>;
  if (!ipo) return null;

  const categories = ORDER.filter((c) => ipo.subscription[c] !== undefined);

  return (
    <div className="container">
      <p style={{ marginTop: 0 }}>
        <Link to="/">← All IPOs</Link>
      </p>

      <h1>{ipo.company_name}</h1>
      <p className="subtitle">
        {ipo.symbol} · {ipo.exchange} · {ipo.board === "SME" ? "SME" : "Mainboard"}
      </p>

      {ipo.is_last_day && (
        <>
          <div className="alert-banner">
            ⚠️ Last day to apply — applications typically cut off at 5:00 PM IST.
          </div>
          <div style={{ marginBottom: 20 }}>
            <Countdown closeDate={ipo.close_date} />
          </div>
        </>
      )}

      <div className="stack">
        <div className="card reveal">
          <div style={{ display: "flex", gap: 16, alignItems: "center", marginBottom: 14 }}>
            <ScoreRing score={ipo.score} size={72} stroke={7} />
            <div>
              <h2 style={{ margin: 0 }}>Issue details</h2>
              <p className="muted" style={{ margin: "2px 0 0", fontSize: 13 }}>
                Listing outlook shown left — full breakdown below.
              </p>
            </div>
          </div>
          <div className="stats" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" }}>
            <div>
              <div className="stat-label">Price band</div>
              <div className="stat-value">
                {ipo.price_band_min && ipo.price_band_max
                  ? `${formatMoney(ipo.price_band_min)}–${formatMoney(ipo.price_band_max)}`
                  : "—"}
              </div>
            </div>
            <div>
              <div className="stat-label">Lot size</div>
              <div className="stat-value">{ipo.lot_size ?? "—"}</div>
            </div>
            <div>
              <div className="stat-label">Min investment</div>
              <div className="stat-value">{formatMoney(ipo.min_investment)}</div>
            </div>
            <div>
              <div className="stat-label">Opens</div>
              <div className="stat-value">{formatDate(ipo.open_date)}</div>
            </div>
            <div>
              <div className="stat-label">Closes</div>
              <div className="stat-value">{formatDate(ipo.close_date)}</div>
            </div>
            <div>
              <div className="stat-label">Listing</div>
              <div className="stat-value">{formatDate(ipo.listing_date)}</div>
            </div>
            <div>
              <div className="stat-label">Registrar</div>
              <div className="stat-value" style={{ fontSize: 13, whiteSpace: "normal" }}>
                {ipo.registrar ?? "—"}
              </div>
            </div>
            <div>
              <div className="stat-label">Status</div>
              <div className="stat-value">{ipo.status}</div>
            </div>
          </div>
        </div>

        <div className="card">
          <h2>Grey market premium &amp; listing estimate</h2>
          {ipo.gmp?.gmp_value != null ? (
            <div className="stats" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" }}>
              <div>
                <div className="stat-label">GMP</div>
                <div className="stat-value">{formatMoney(ipo.gmp.gmp_value)}</div>
              </div>
              <div>
                <div className="stat-label">Est. listing price</div>
                <div className="stat-value">{formatMoney(ipo.estimated_listing_price)}</div>
              </div>
              <div>
                <div className="stat-label">Expected gain</div>
                <div
                  className={`stat-value${
                    ipo.expected_gain_pct === null
                      ? ""
                      : ipo.expected_gain_pct >= 0
                        ? " good"
                        : " bad"
                  }`}
                >
                  {ipo.expected_gain_pct !== null
                    ? `${ipo.expected_gain_pct >= 0 ? "+" : ""}${ipo.expected_gain_pct.toFixed(2)}%`
                    : "—"}
                </div>
              </div>
              <div>
                <div className="stat-label">Source</div>
                <div className="stat-value" style={{ fontSize: 13 }}>
                  {ipo.gmp.source}
                </div>
              </div>
            </div>
          ) : (
            <p className="muted">
              No GMP data. Configure a GMP provider on the server to populate this — NSE does not
              publish grey market data, since the grey market is unofficial and off-exchange.
            </p>
          )}
        </div>

        <div className="card">
          <h2>Subscription by category</h2>
          {categories.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th className="num">Times subscribed</th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map((c) => (
                    <tr key={c}>
                      <td>{CATEGORY_LABELS[c] ?? c}</td>
                      <td className="num">
                        <strong>{formatTimes(ipo.subscription[c])}</strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">Bidding has not opened yet.</p>
          )}
        </div>

        <div className="card">
          <h2>Subscription over time</h2>
          <SubscriptionChart history={ipo.subscription_history} />
        </div>

        <ScoreBreakdown score={ipo.score} />
      </div>

      <div className="disclaimer">
        <strong>Informational only — not investment advice.</strong> Figures are sourced from NSE
        and third-party grey market data and may be delayed or incorrect. GMP is unofficial and
        unregulated. Verify against the RHP and your broker before applying.
      </div>
    </div>
  );
}
