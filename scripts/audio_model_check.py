"""Replay existing PCM through the shipped pretrained audio classifier; no training."""

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
from server.domain import DEFAULT_THRESHOLDS  # noqa: E402
from server.recording import load_timeline, safe_session  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "reports/local-audio-model-check.json"
    )
    args = parser.parse_args()
    if not 1 < args.seconds <= 120:
        parser.error("--seconds must be greater than 1 and at most 120")
    folder = safe_session(ROOT / "recordings", args.session)
    metadata = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    rows = [row for row in load_timeline(folder) if row["kind"] == "audio"]
    if not rows:
        parser.error("session has no audio")
    # Use the verified W channel only when this recording matches the saved
    # camera and capture configuration. Otherwise retain ordinary downmix.
    calibration_file = ROOT / "runtime/calibration.json"
    calibration = (
        json.loads(calibration_file.read_text(encoding="utf-8"))
        if calibration_file.exists()
        else {}
    )
    config = metadata.get("config", {})
    first_pcm = np.load(folder / rows[0]["file"], allow_pickle=False)
    mono_channel = (
        calibration["mapping"]["w"]
        if calibration.get("rotation_verified")
        and rows[0]["source"] == "camera"
        and first_pcm.ndim == 2
        and first_pcm.shape[1] == 4
        and calibration.get("serial") == metadata.get("native", {}).get("serial")
        and calibration.get("audio_profile") == config.get("audio_profile")
        and calibration.get("camera_microphone") == config.get("camera_microphone")
        and calibration.get("sample_rate") == rows[0]["rate"]
        and calibration.get("channels") == 4
        else None
    )
    model, window, samples = Classifier(ROOT / "models/yamnet"), AudioWindow(), []
    thresholds = {
        category: config.get("thresholds", {}).get(category, default)
        for category, default in DEFAULT_THRESHOLDS.items()
    }
    origin = rows[0]["timestamp"]
    for row in rows:
        now = row["timestamp"] - origin
        if now > args.seconds:
            break
        pcm = np.load(folder / row["file"], allow_pickle=False)
        window.append(pcm, row["rate"], row["source"], now, mono_channel=mono_channel)
        if not window.ready(now):
            continue
        window.last_infer = now
        started = time.perf_counter()
        scores = model.infer(window.samples)
        samples.append(
            dict(
                offset_seconds=round(now, 3),
                inference_ms=round((time.perf_counter() - started) * 1000, 2),
                scores={key: round(value, 4) for key, value in scores.items()},
            )
        )
    if not samples:
        parser.error("not enough contiguous audio for classification")
    timings = [item["inference_ms"] for item in samples]
    report = dict(
        model="Google YAMNet pretrained SavedModel, 521 AudioSet classes",
        session=args.session,
        seconds=args.seconds,
        model_calls=len(samples),
        analysis_window_ms=960,
        mono_input="verified_ambisonic_w" if mono_channel is not None else "channel_average",
        model_inference_p50_ms=round(float(np.median(timings)), 2),
        model_inference_p95_ms=round(float(np.percentile(timings, 95)), 2),
        thresholds=thresholds,
        windows_above_threshold={
            category: sum(row["scores"][category] >= threshold for row in samples)
            for category, threshold in thresholds.items()
        },
        accuracy_measured=False,
        end_to_end_latency_measured=False,
        note="按录制时间重放原始 PCM 的分类与模型耗时；无逐类起止标注，窗口数不等于事件数或准确率。",
        samples=samples,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "samples"}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
