"""Scoring heuristic.

The property that matters most is honesty: the score must never look confident
when the inputs don't support it.
"""

from app.services.scoring import compute_score, estimate_listing


def test_no_inputs_scores_none_not_fifty():
    """A neutral-looking 50 from zero data would be actively misleading."""
    result = compute_score()
    assert result.score is None
    assert result.confidence == 0.0
    assert "Not enough data" in result.notes[0]


def test_strong_ipo_scores_high():
    result = compute_score(
        gmp_pct=45.0, qib_times=60.0, nii_times=40.0, retail_times=8.0, total_times=42.0
    )
    assert result.score is not None and result.score >= 80


def test_weak_ipo_scores_low():
    result = compute_score(
        gmp_pct=0.0, qib_times=0.2, nii_times=0.3, retail_times=0.4, total_times=0.3
    )
    assert result.score is not None and result.score <= 15


def test_negative_gmp_zeroes_that_component_and_is_flagged():
    result = compute_score(gmp_pct=-8.0, total_times=2.0)
    gmp = next(c for c in result.components if c.key == "gmp")
    assert gmp.score == 0.0
    assert any("negative" in n for n in result.notes)


def test_confidence_reflects_missing_inputs():
    partial = compute_score(total_times=3.0)
    full = compute_score(
        gmp_pct=15.0,
        gmp_pct_previous=10.0,
        qib_times=5.0,
        nii_times=4.0,
        retail_times=2.0,
        total_times=4.0,
    )
    assert partial.confidence < full.confidence
    assert full.confidence == 1.0


def test_missing_gmp_is_called_out():
    result = compute_score(qib_times=5.0, total_times=4.0)
    assert any("No GMP data" in n for n in result.notes)


def test_subscription_curve_saturates():
    """Diminishing returns: 30x to 60x must move the needle less than 0x to 30x."""
    low = compute_score(total_times=0.0).score or 0
    mid = compute_score(total_times=30.0).score or 0
    high = compute_score(total_times=60.0).score or 0
    assert mid - low > high - mid


def test_gmp_momentum_direction():
    rising = compute_score(gmp_pct=20.0, gmp_pct_previous=10.0)
    falling = compute_score(gmp_pct=20.0, gmp_pct_previous=30.0)
    assert rising.score is not None and falling.score is not None
    assert rising.score > falling.score

    trend = next(c for c in rising.components if c.key == "gmp_trend")
    assert "rising" in trend.detail


def test_components_carry_their_weights_for_display():
    result = compute_score(gmp_pct=10.0, qib_times=5.0)
    assert {c.key for c in result.components} == {"gmp", "qib"}
    assert all(c.weight > 0 and c.detail for c in result.components)


def test_score_is_bounded():
    extreme = compute_score(
        gmp_pct=500.0, qib_times=900.0, nii_times=900.0, retail_times=900.0, total_times=900.0
    )
    assert extreme.score is not None and 0 <= extreme.score <= 100


# --------------------------------------------------------------------------- #
# Listing estimate - plain arithmetic, no modelling
# --------------------------------------------------------------------------- #


def test_estimate_listing():
    assert estimate_listing(100.0, 25.0) == {
        "estimated_listing_price": 125.0,
        "expected_gain_pct": 25.0,
    }


def test_estimate_listing_handles_missing_inputs():
    assert estimate_listing(None, 25.0)["estimated_listing_price"] is None
    assert estimate_listing(100.0, None)["expected_gain_pct"] is None


def test_estimate_listing_handles_discount():
    result = estimate_listing(200.0, -20.0)
    assert result["estimated_listing_price"] == 180.0
    assert result["expected_gain_pct"] == -10.0
