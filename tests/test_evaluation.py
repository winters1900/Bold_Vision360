from scripts.evaluate import summarize


def complete_sheet():
    rows = [
        dict(
            condition=condition,
            category=category,
            angle_deg=angle,
            repetition=repetition,
            observed=1,
            detected=0,
        )
        for condition in ("quiet", "traffic_noise")
        for category in ("horn", "siren", "shout")
        for angle in range(0, 360, 45)
        for repetition in range(1, 6)
    ]
    rows.append(
        dict(
            condition="quiet",
            category="negative",
            observed=1,
            negative_minutes=10,
            false_positive_count=0,
        )
    )
    return rows


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


def test_complete_measurements_require_exact_240_case_matrix_and_negative_count():
    rows = complete_sheet()
    result = summarize(rows)
    assert result["status"] == "complete_measurements"
    assert result["recall"] == 0 and result["direction_unknown_trials"] == 240
    rows[0] = rows[1].copy()
    result = summarize(rows)
    assert result["status"] == "not_fully_measured"
    assert result["duplicate_planned_trials"] == result["missing_planned_trials"] == 1


def test_blank_detection_latency_or_negative_count_cannot_complete_report():
    rows = complete_sheet()
    rows[0]["detected"] = ""
    result = summarize(rows)
    assert result["status"] == "not_fully_measured"
    assert result["detection_unrecorded_trials"] == 1
    rows[0]["detected"] = 1
    result = summarize(rows)
    assert result["status"] == "not_fully_measured"
    assert result["latency_missing_detected_trials"] == 1
    rows[0].update(onset_ms=0, hud_ms=800)
    rows[-1]["false_positive_count"] = ""
    result = summarize(rows)
    assert result["status"] == "not_fully_measured"
    assert result["negative_rows_missing_counts"] == 1
    assert result["false_positives_per_5_minutes"] is None
    rows[-1].update(false_positive_count=0, condition="traffic_noise")
    assert summarize(rows)["status"] == "not_fully_measured"
