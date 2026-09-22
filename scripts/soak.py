"""Observe a real running session; never substitutes synthetic events for measurements."""

import argparse
import json
import time
from pathlib import Path
import statistics
import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=600)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    (root / "reports").mkdir(exist_ok=True)
    start = time.monotonic()
    samples = []
    while time.monotonic() - start < args.seconds:
        try:
            s = requests.get("http://127.0.0.1:8765/api/status", timeout=3).json()
            samples.append(
                {
                    k: s.get(k)
                    for k in (
                        "mode",
                        "phase",
                        "fps",
                        "frame_age_ms",
                        "audio_source",
                        "channels",
                        "audio_rate",
                        "detection_ms",
                        "audio_inference_ms",
                        "audio_drops",
                        "error",
                        "clock_diagnostics",
                    )
                }
            )
        except Exception as exc:
            samples.append({"error": str(exc)})
        time.sleep(2)
    good = [
        s
        for s in samples
        if s.get("phase") == "running"
        and s.get("frame_age_ms") is not None
        and s["frame_age_ms"] < 2000
    ]
    report = {
        "duration_seconds": round(time.monotonic() - start),
        "samples": len(samples),
        "healthy_samples": len(good),
        "passed": len(good) == len(samples),
        "median_fps": statistics.median(s["fps"] for s in good) if good else None,
        "note": "Unlabelled indoor live observation; NOT a quiet-negative or recall/direction/alert-latency test.",
        "observations": samples,
    }
    (root / "reports/local-soak.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "observations"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
