"""Make a 240-trial worksheet or evaluate labelled measurements, never invented results."""

import argparse
import csv
import json
import math
from pathlib import Path
import numpy as np

FIELDS = [
    "trial",
    "condition",
    "category",
    "angle_deg",
    "repetition",
    "observed",
    "detected",
    "predicted_angle_deg",
    "onset_ms",
    "hud_ms",
    "false_positive_count",
    "negative_minutes",
    "notes",
]
CONDITIONS = ("quiet", "traffic_noise")
CATEGORIES = ("horn", "siren", "shout")
ANGLES = tuple(range(0, 360, 45))
REPETITIONS = tuple(range(1, 6))
EXPECTED = {
    (condition, category, angle, repetition)
    for condition in CONDITIONS
    for category in CATEGORIES
    for angle in ANGLES
    for repetition in REPETITIONS
}


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def nonnegative_integer(value):
    parsed = number(value)
    return int(parsed) if parsed is not None and parsed >= 0 and parsed.is_integer() else None


def planned_key(row):
    angle = nonnegative_integer(row.get("angle_deg"))
    repetition = nonnegative_integer(row.get("repetition"))
    return (row.get("condition"), row.get("category"), angle, repetition)


def summarize(rows):
    measured = [r for r in rows if str(r.get("observed", "")).lower() in ("1", "true")]
    positive = [r for r in measured if r.get("category") != "negative"]
    detected = [r for r in positive if str(r.get("detected", "")).lower() in ("1", "true")]
    keys = [planned_key(row) for row in positive]
    valid_keys = [key for key in keys if key in EXPECTED]
    detection_unrecorded = sum(
        str(row.get("detected", "")).lower() not in ("0", "1", "true", "false") for row in positive
    )
    errors, delays = [], []
    invalid_values = 0
    for row in detected:
        invalid_row = False
        actual = number(row.get("angle_deg"))
        predicted = number(row.get("predicted_angle_deg"))
        if row.get("predicted_angle_deg") not in ("", None):
            if actual is None or predicted is None or not 0 <= predicted <= 360:
                invalid_row = True
            else:
                errors.append(abs((predicted - actual + 180) % 360 - 180))
        onset = number(row.get("onset_ms"))
        hud = number(row.get("hud_ms"))
        if onset is not None and hud is not None and 0 <= onset <= hud:
            delays.append(hud - onset)
        elif row.get("onset_ms") not in ("", None) or row.get("hud_ms") not in ("", None):
            invalid_row = True
        invalid_values += invalid_row
    negative = [r for r in measured if r.get("category") == "negative"]
    valid_negative = [
        (duration, count)
        for row in negative
        if row.get("condition") == "quiet"
        and (duration := number(row.get("negative_minutes"))) is not None
        and duration > 0
        and (count := nonnegative_integer(row.get("false_positive_count"))) is not None
    ]
    minutes = sum(duration for duration, _ in valid_negative)
    fp = sum(count for _, count in valid_negative)
    duplicate_trials = len(valid_keys) - len(set(valid_keys))
    missing_trials = len(EXPECTED - set(valid_keys))
    unexpected_trials = len(positive) - len(valid_keys)
    latency_missing = len(detected) - len(delays)
    complete = (
        len(positive) == len(EXPECTED)
        and missing_trials == 0
        and duplicate_trials == 0
        and unexpected_trials == 0
        and detection_unrecorded == 0
        and invalid_values == 0
        and latency_missing == 0
        and len(valid_negative) == len(negative)
        and minutes >= 10
    )
    return {
        "planned_positive_trials": len(EXPECTED),
        "measured_positive_trials": len(positive),
        "detected_trials": len(detected),
        "missed_trials": len(positive) - len(detected),
        "detection_unrecorded_trials": detection_unrecorded,
        "missing_planned_trials": missing_trials,
        "duplicate_planned_trials": duplicate_trials,
        "unexpected_planned_trials": unexpected_trials,
        "invalid_value_rows": invalid_values,
        "direction_unknown_trials": len(positive) - len(errors),
        "recall": len(detected) / len(positive) if positive else None,
        "direction_median_error_deg": float(np.median(errors)) if errors else None,
        "direction_coverage": len(errors) / len(positive) if positive else None,
        "alert_latency_p95_ms": float(np.percentile(delays, 95)) if delays else None,
        "latency_measured_trials": len(delays),
        "latency_missing_detected_trials": latency_missing,
        "negative_minutes": minutes,
        "negative_rows_missing_counts": len(negative) - len(valid_negative),
        "false_positives_per_5_minutes": fp / minutes * 5 if minutes else None,
        "status": "complete_measurements" if complete else "not_fully_measured",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("reports/field-results.json"))
    args = parser.parse_args()
    if args.template:
        args.template.parent.mkdir(parents=True, exist_ok=True)
        with args.template.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            trial = 0
            for condition in CONDITIONS:
                for category in CATEGORIES:
                    for angle in ANGLES:
                        for repetition in REPETITIONS:
                            trial += 1
                            writer.writerow(
                                dict(
                                    trial=trial,
                                    condition=condition,
                                    category=category,
                                    angle_deg=angle,
                                    repetition=repetition,
                                    observed=0,
                                )
                            )
            writer.writerow(
                dict(trial="negative-10min", condition="quiet", category="negative", observed=0)
            )
    if args.input:
        with args.input.open(encoding="utf-8-sig") as f:
            result = summarize(list(csv.DictReader(f)))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(result)


if __name__ == "__main__":
    main()
