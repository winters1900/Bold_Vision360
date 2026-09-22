from scripts.evaluate import summarize


def test_unknown_and_missed_not_removed_from_denominator():
    result = summarize(
        [
            dict(
                observed=1,
                detected=1,
                category="horn",
                angle_deg=0,
                predicted_angle_deg="",
                onset_ms=0,
                hud_ms=1000,
            ),
            dict(observed=1, detected=0, category="horn", angle_deg=90),
        ]
    )
    assert result["recall"] == 0.5
    assert result["direction_unknown_trials"] == 2 and result["direction_median_error_deg"] is None
    assert result["alert_latency_p95_ms"] == 1000
    assert result["status"] == "not_fully_measured"


def test_unmeasured_sheet_has_no_fabricated_metrics():
    result = summarize([dict(observed=0, category="horn")])
    assert result["recall"] is None and result["false_positives_per_5_minutes"] is None
