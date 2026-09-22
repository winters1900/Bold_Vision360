"""Make a 240-trial worksheet or evaluate labelled measurements, never invented results."""

import argparse
import csv
import json
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


def summarize(rows):
    measured = [r for r in rows if str(r.get("observed", "")).lower() in ("1", "true")]
    positive = [r for r in measured if r.get("category") != "negative"]
    detected = [r for r in positive if str(r.get("detected", "")).lower() in ("1", "true")]
    errors = [
        abs((float(r["predicted_angle_deg"]) - float(r["angle_deg"]) + 180) % 360 - 180)
        for r in detected
        if r.get("predicted_angle_deg") not in ("", None)
    ]
    delays = [
        float(r["hud_ms"]) - float(r["onset_ms"])
        for r in detected
        if r.get("hud_ms") not in ("", None) and r.get("onset_ms") not in ("", None)
    ]
    negative = [r for r in measured if r.get("category") == "negative"]
    minutes = sum(float(r.get("negative_minutes") or 0) for r in negative)
    fp = sum(int(r.get("false_positive_count") or 0) for r in negative)
    return {
        "planned_positive_trials": 240,
        "measured_positive_trials": len(positive),
        "detected_trials": len(detected),
        "missed_trials": len(positive) - len(detected),
        "direction_unknown_trials": len(positive) - len(errors),
        "recall": len(detected) / len(positive) if positive else None,
        "direction_median_error_deg": float(np.median(errors)) if errors else None,
        "direction_coverage": len(errors) / len(positive) if positive else None,
        "alert_latency_p95_ms": float(np.percentile(delays, 95)) if delays else None,
        "latency_measured_trials": len(delays),
        "negative_minutes": minutes,
        "false_positives_per_5_minutes": fp / minutes * 5 if minutes else None,
        "status": "complete_measurements"
        if len(positive) == 240 and minutes >= 10
        else "not_fully_measured",
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
            for condition in ("quiet", "traffic_noise"):
                for category in ("horn", "siren", "shout"):
                    for angle in range(0, 360, 45):
                        for repetition in range(1, 6):
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
