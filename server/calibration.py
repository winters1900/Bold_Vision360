"""Persist labelled raw PCM so a service restart does not lose physical captures."""

import json
import math
import numpy as np
from .domain import delta


DIRECTION_ERROR_LIMIT = 22.5


def calibration_quality(data):
    """Mapping identification and usable HUD accuracy are separate conditions.

    Check each cardinal, not just a mean that hides a wrong adjacent sector.
    Recompute errors from measurements so older persisted fits are gated too.
    This is an engineering gate, not a substitute for held-out field trials.
    """
    result = dict(
        passed=False,
        limit_deg=DIRECTION_ERROR_LIMIT,
        failed_angles=[],
        max_error_deg=None,
        reason="尚未完成方向标定",
    )
    if not data:
        return result
    rows = data.get("estimates", [])
    if len(rows) != 4 or {r.get("target") for r in rows} != {0, 90, 180, 270}:
        result["reason"] = "缺少逐方位精度记录，请重新采样"
        return result
    errors = []
    for row in rows:
        angle, confidence = row.get("measured"), row.get("confidence")
        if (
            not isinstance(angle, (int, float))
            or not isinstance(confidence, (int, float))
            or not math.isfinite(angle)
            or not math.isfinite(confidence)
        ):
            result["reason"] = "方向标定记录无效，请重新采样"
            return result
        error = abs(delta(angle, row["target"]))
        errors.append(error)
        if error > DIRECTION_ERROR_LIMIT or confidence < 0.2:
            result["failed_angles"].append(row["target"])
    result["max_error_deg"] = max(errors)
    if result["failed_angles"]:
        labels = {0: "前方", 90: "右侧", 180: "后方", 270: "左侧"}
        names = "、".join(labels[a] for a in result["failed_angles"])
        result["reason"] = f"{names}未达到逐方位误差 ≤22.5°、置信度 ≥0.2 的门槛；暂不使用音频方位"
        return result
    rotation = data.get("rotation") or {}
    measured, confidence = rotation.get("measured"), rotation.get("confidence")
    if (
        not data.get("rotation_verified")
        or not isinstance(measured, (int, float))
        or not isinstance(confidence, (int, float))
        or not math.isfinite(measured)
        or not math.isfinite(confidence)
        or confidence < 0.2
        or abs(delta(measured, 270)) > DIRECTION_ERROR_LIMIT
    ):
        result["reason"] = "逐方位门槛已满足，仍需通过独立转动验证"
        return result
    result.update(passed=True, reason="逐方位与转动门槛已满足；完整现场精度尚待验收")
    return result


def capture_binding(native, config, rate, channels):
    return {
        "serial": native.get("serial"),
        "audio_profile": config.get("audio_profile", "unknown"),
        "camera_microphone": config.get("camera_microphone", "unknown"),
        "sample_rate": rate,
        "channels": channels,
    }


def save_samples(path, samples, binding):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as f:
        np.savez_compressed(
            f, metadata=json.dumps(binding), **{str(a): p for a, p in samples.items()}
        )
    temporary.replace(path)


def load_samples(path, binding):
    if not path.exists():
        return {}
    with np.load(path, allow_pickle=False) as archive:
        if json.loads(str(archive["metadata"])) != binding:
            return {}
        samples = {}
        for angle in (0, 90, 180, 270):
            if str(angle) not in archive:
                continue
            pcm = archive[str(angle)]
            if (
                pcm.ndim != 2
                or pcm.shape[1] != 4
                or len(pcm) < binding["sample_rate"]
                or not np.isfinite(pcm).all()
            ):
                raise ValueError("保存的标定采样无效，请重新标定")
            samples[angle] = pcm
        return samples
