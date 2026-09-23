"""Audit four labelled recordings and a separate clockwise-90-degree holdout.

Does not enable direction or modify the running service. All sessions must use
the same camera, microphone, declared mode and actual PCM format.
"""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.audio import covariance_intensity, fit_axes, intensity  # noqa: E402
from server.calibration import calibration_quality, capture_binding  # noqa: E402
from server.domain import delta  # noqa: E402
from server.recording import load_timeline, safe_session  # noqa: E402


def read_capture(session):
    folder = safe_session(ROOT / "recordings", session)
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    rows = [r for r in load_timeline(folder) if r["kind"] == "audio"]
    rates = {r["rate"] for r in rows}
    if len(rates) != 1 or {r["source"] for r in rows} != {"camera"}:
        raise ValueError("录制必须包含同一采样率的相机音频")
    if any(b["timestamp"] - a["timestamp"] > 0.35 for a, b in zip(rows, rows[1:])):
        raise ValueError("录制音频存在中断")
    rate = rates.pop()
    pcm = np.concatenate([np.load(folder / r["file"], allow_pickle=False) for r in rows])
    if pcm.ndim != 2 or pcm.shape[1] != 4 or len(pcm) < rate:
        raise ValueError("每段录制至少需要一秒四声道音频")
    return pcm, capture_binding(meta["native"], meta["config"], rate, 4)


def audit(sessions):
    captures = [read_capture(s) for s in sessions]
    binding = captures[0][1]
    if not binding["serial"] or any(b != binding for _, b in captures):
        raise ValueError("录制的相机或收音配置不一致")
    rate = binding["sample_rate"]
    samples = dict(zip((0, 90, 180, 270), [p for p, _ in captures[:4]]))
    fit = fit_axes(samples, rate)
    # Freeze the mapping before evaluating the independent rotation recording.
    pcm = captures[4][0]
    angle, confidence = intensity(pcm, fit["mapping"], rate)
    rotation = dict(
        target=270, measured=angle, confidence=confidence, error_deg=abs(delta(angle, 270))
    )
    passed = confidence >= 0.2 and rotation["error_deg"] <= 22.5
    windows = []
    size, step = round(rate * 0.3), round(rate * 0.1)
    for start in range(0, len(pcm) - size + 1, step):
        angle, confidence = intensity(pcm[start : start + size], fit["mapping"], rate)
        windows.append(
            dict(measured=angle, confidence=confidence, error_deg=abs(delta(angle, 270)))
        )
    baseline = []
    for target, p in samples.items():
        angle, confidence = covariance_intensity(np.cov(p, rowvar=False, bias=True), fit["mapping"])
        baseline.append(
            dict(
                target=target,
                measured=angle,
                confidence=confidence,
                error_deg=abs(delta(angle, target)),
            )
        )
    calibration = {**fit, **binding, "rotation": rotation, "rotation_verified": passed}
    quality = calibration_quality(calibration)
    return dict(
        passed=quality["passed"],
        mapping_rotation_passed=passed,
        quality=quality,
        field_accuracy_measured=False,
        binding=binding,
        sessions=dict(zip(("front", "right", "rear", "left", "rotation"), sessions)),
        unfiltered_estimates=baseline,
        calibration=calibration,
        rotation_windows=windows,
        note="四方位为拟合样本；转动录制为独立验证。重叠窗口不是独立试次，不能代替 240 次现场验收。",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sessions", nargs=5, help="依次为前、右、后、左、转动的录制会话 ID")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "reports/local-spatial-calibration.json"
    )
    args = parser.parse_args()
    try:
        result = audit(args.sessions)
    except (ValueError, OSError, KeyError) as exc:
        result = dict(
            passed=False, field_accuracy_measured=False, sessions=args.sessions, error=str(exc)
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            dict(passed=result["passed"], output=str(args.output), error=result.get("error"))
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
