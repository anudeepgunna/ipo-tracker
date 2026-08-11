"""Listing-outlook scoring.

This is a **transparent heuristic, not a prediction**. It blends signals that
historically correlate with a positive listing - grey market premium, how heavily
each investor category bid, and whether GMP is rising or falling - into a 0-100
number, and returns every component alongside it so the UI can show its work.

Deliberate design choices:

* Every component is optional. A brand-new IPO with no bids and no GMP scores
  `None`, not 50 - a confident-looking number built from no data is worse than
  an honest "not enough data yet".
* Weights are renormalised over whichever components are available, so a missing
  GMP provider degrades the score's confidence rather than silently dragging it
  toward zero.
* QIB carries the largest subscription weight. Institutional demand is the most
  informative category because QIBs do the deepest diligence and cannot withdraw
  bids once placed, unlike retail.

None of this is investment advice. GMP in particular is an unofficial, thinly
traded, easily manipulated indicator.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

# component -> weight. Renormalised over whatever is actually available.
WEIGHTS = {
    "gmp": 0.35,
    "qib": 0.25,
    "total": 0.15,
    "retail": 0.10,
    "nii": 0.05,
    "gmp_trend": 0.10,
}


@dataclass
class Component:
    key: str
    label: str
    raw: float | None
    score: float  # 0-100 contribution before weighting
    weight: float
    detail: str


@dataclass
class ScoreResult:
    score: int | None
    confidence: float  # 0-1: share of total weight backed by real data
    components: list[Component]
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "confidence": round(self.confidence, 2),
            "components": [asdict(c) for c in self.components],
            "notes": self.notes,
        }


def _saturating(value: float, midpoint: float) -> float:
    """Map [0, inf) to [0, 100), reaching 50 at `midpoint`.

    Subscription and GMP both have strongly diminishing returns: 60x subscribed is
    not twice as good a signal as 30x, but 3x is meaningfully better than 1.5x. A
    saturating curve captures that far better than a linear scale with a hard cap.
    """
    if value <= 0:
        return 0.0
    return 100.0 * (1.0 - math.exp(-math.log(2) * value / midpoint))


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def compute_score(
    *,
    gmp_pct: float | None = None,
    gmp_pct_previous: float | None = None,
    qib_times: float | None = None,
    nii_times: float | None = None,
    retail_times: float | None = None,
    total_times: float | None = None,
) -> ScoreResult:
    """Blend available signals into a 0-100 outlook with a full breakdown."""
    components: list[Component] = []
    notes: list[str] = []

    # --- GMP level: premium as a percentage of issue price ---
    if gmp_pct is not None:
        # A 20% premium is a strong signal; the curve hits 50 there and saturates.
        raw_score = _saturating(max(gmp_pct, 0.0), midpoint=20.0)
        if gmp_pct < 0:
            raw_score = 0.0
            notes.append("GMP is negative - the grey market implies a discount to issue price.")
        components.append(
            Component(
                key="gmp",
                label="Grey market premium",
                raw=gmp_pct,
                score=raw_score,
                weight=WEIGHTS["gmp"],
                detail=f"{gmp_pct:+.1f}% over issue price",
            )
        )

    # --- GMP trend: is the premium building or bleeding? ---
    if gmp_pct is not None and gmp_pct_previous is not None:
        delta = gmp_pct - gmp_pct_previous
        # +-10pp of movement spans the full range, centred at 50 for "flat".
        trend_score = _clamp(50.0 + delta * 5.0)
        direction = "rising" if delta > 0.5 else "falling" if delta < -0.5 else "flat"
        components.append(
            Component(
                key="gmp_trend",
                label="GMP momentum",
                raw=delta,
                score=trend_score,
                weight=WEIGHTS["gmp_trend"],
                detail=f"{direction} ({delta:+.1f}pp vs earlier reading)",
            )
        )

    # --- Subscription by category ---
    # Midpoints reflect what "healthy" looks like per category: institutions
    # routinely go to double digits, retail rarely does.
    for key, label, value, midpoint in (
        ("qib", "QIB subscription", qib_times, 10.0),
        ("nii", "NII subscription", nii_times, 10.0),
        ("retail", "Retail subscription", retail_times, 3.0),
        ("total", "Total subscription", total_times, 6.0),
    ):
        if value is None:
            continue
        components.append(
            Component(
                key=key,
                label=label,
                raw=value,
                score=_saturating(value, midpoint=midpoint),
                weight=WEIGHTS[key],
                detail=f"{value:.2f}x subscribed",
            )
        )

    if not components:
        return ScoreResult(
            score=None,
            confidence=0.0,
            components=[],
            notes=["Not enough data yet - bidding has not opened and no GMP is available."],
        )

    available_weight = sum(c.weight for c in components)
    weighted = sum(c.score * c.weight for c in components) / available_weight
    confidence = available_weight / sum(WEIGHTS.values())

    if confidence < 0.5:
        notes.append("Low confidence - several inputs are still missing.")
    if gmp_pct is None:
        notes.append("No GMP data available; score is based on subscription only.")

    return ScoreResult(
        score=int(round(_clamp(weighted))),
        confidence=confidence,
        components=components,
        notes=notes,
    )


def estimate_listing(issue_price: float | None, gmp_value: float | None) -> dict:
    """Straight arithmetic on the grey market premium - no modelling involved."""
    if issue_price is None or gmp_value is None:
        return {"estimated_listing_price": None, "expected_gain_pct": None}
    return {
        "estimated_listing_price": round(issue_price + gmp_value, 2),
        "expected_gain_pct": round(gmp_value / issue_price * 100, 2) if issue_price else None,
    }
