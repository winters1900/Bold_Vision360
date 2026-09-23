"""Offline local-processing comparison using recorded PCM; no accuracy claims."""

import argparse
import json
import os
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
from server.audio import AudioWindow, Classifier  # noqa: E402
from server.noise import classify_views  # noqa: E402
from server.recording import safe_session, load_timeline  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/local-audio-ab.json")
    args = parser.parse_args()
    if not 1 < args.seconds <= 120:
        parser.error("--seconds must be greater than 1 and at most 120")
    folder = safe_session(ROOT / "recordings", args.session)
    metadata = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    rows = [r for r in load_timeline(folder) if r["kind"] == "audio"]
    if not rows:
        parser.error("session has no audio")
    model, window, observations = Classifier(ROOT / "models/yamnet"), AudioWindow(), []
    origin = rows[0]["timestamp"]
    for row in rows:
        now = row["timestamp"] - origin
        if now > args.seconds:
            break
        pcm = np.load(folder / row["file"], allow_pickle=False)
        window.append(pcm, row["rate"], row["source"], now, "lowcut_80hz")
        if not window.ready(now):
            continue
        window.last_infer = now
        start = time.perf_counter()
        comparison = classify_views(model, window.samples, window.processed_samples)
        observations.append(
            dict(
                offset_seconds=now, **comparison, inference_ms=(time.perf_counter() - start) * 1000
            )
        )
    if not observations:
        parser.error("not enough contiguous audio for classification")
    thresholds = metadata.get("config", {}).get("thresholds", {})
    summary = {}
    for category in observations[0]["reference_scores"]:
        original = [o["reference_scores"][category] for o in observations]
        filtered = [o["processed_scores"][category] for o in observations if o["processed_scores"]]
        threshold = thresholds.get(category)
        summary[category] = dict(
            reference_mean=float(np.mean(original)),
            filtered_mean=float(np.mean(filtered)) if filtered else None,
            threshold=threshold,
            reference_windows_above_threshold=sum(v >= threshold for v in original)
            if threshold is not None
            else None,
            filtered_windows_above_threshold=sum(v >= threshold for v in filtered)
            if threshold is not None
            else None,
        )
    report = dict(
        session=args.session,
        declared_camera_profile=metadata.get("config", {}).get("audio_profile", "unknown"),
        local_processing="lowcut_80hz",
        synthetic_audio=False,
        accuracy_measured=False,
        note="同一录制的软件处理对比，未比较机身模式；无标注，不推断召回率或降噪收益。",
        windows=len(observations),
        summary=summary,
        dual_inference_p95_ms=float(np.percentile([o["inference_ms"] for o in observations], 95)),
        observations=observations,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "observations"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
