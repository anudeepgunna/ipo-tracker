import { useState } from "react";

import { formatMoney } from "../lib/api";
import type { IpoDetail } from "../lib/types";

/**
 * How many lots a budget buys, and what it actually costs.
 *
 * Worth its space because the arithmetic is genuinely awkward under time
 * pressure: applications must be in whole lots, retail is capped at ₹2,00,000,
 * and the amount blocked is always computed at the cap price regardless of what
 * you bid — so "I have ₹50,000" does not map to an obvious number of lots.
 */
const RETAIL_CAP = 200_000;

export function LotCalculator({ ipo }: { ipo: IpoDetail }) {
  const [budget, setBudget] = useState(100_000);

  const price = ipo.price_band_max ?? ipo.price_band_min;
  if (!ipo.lot_size || !price) {
    return null;
  }

  const perLot = ipo.lot_size * price;
  const affordable = Math.floor(budget / perLot);
  // Retail applications cannot exceed ₹2 lakh; beyond it you bid as an HNI/NII.
  const retailMaxLots = Math.floor(RETAIL_CAP / perLot);
  const lots = Math.min(affordable, retailMaxLots);
  const blocked = lots * perLot;
  const leftover = budget - blocked;
  const cappedByRetail = affordable > retailMaxLots;

  return (
    <div className="card">
      <h2>How many lots can I apply for?</h2>

      <div className="field">
        <label htmlFor="budget">Your budget</label>
        <input
          id="budget"
          type="number"
          min={0}
          step={1000}
          value={budget}
          onChange={(e) => setBudget(Math.max(0, Number(e.target.value) || 0))}
        />
        <div className="pill-list" style={{ marginTop: 8 }}>
          {[perLot, 50_000, 100_000, RETAIL_CAP].map((amount, i) => (
            <button
              key={i}
              className={`chip${budget === Math.round(amount) ? " active" : ""}`}
              onClick={() => setBudget(Math.round(amount))}
            >
              {i === 0 ? "1 lot" : formatMoney(amount)}
            </button>
          ))}
        </div>
      </div>

      <div className="calc-result">
        <div className="calc-lots">
          <span className="calc-lots-num">{lots}</span>
          <span className="muted">{lots === 1 ? "lot" : "lots"}</span>
        </div>
        <div className="calc-detail">
          <div>
            <span className="muted">Shares</span>
            <strong>{(lots * ipo.lot_size).toLocaleString("en-IN")}</strong>
          </div>
          <div>
            <span className="muted">Amount blocked</span>
            <strong>{formatMoney(blocked)}</strong>
          </div>
          <div>
            <span className="muted">Left over</span>
            <strong>{formatMoney(leftover)}</strong>
          </div>
        </div>
      </div>

      {lots === 0 && (
        <p className="muted" style={{ marginBottom: 0 }}>
          One lot costs {formatMoney(perLot)} — the minimum you can apply for.
        </p>
      )}
      {cappedByRetail && (
        <p className="muted" style={{ marginBottom: 0 }}>
          Capped at {retailMaxLots} {retailMaxLots === 1 ? "lot" : "lots"}: retail applications
          can't exceed {formatMoney(RETAIL_CAP)}. Above that you'd apply in the NII category,
          where allotment works differently.
        </p>
      )}
      <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 10 }}>
        Calculated at the cap price of {formatMoney(price)} — the full amount is blocked by
        your UPI mandate even if the issue prices lower.
      </p>
    </div>
  );
}
