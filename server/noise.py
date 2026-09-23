"""Optional classification-only filtering. SDK PCM is never modified in place."""

import numpy as np
from scipy.signal import butter, sosfilt

CAMERA_PROFILES = {
    "unknown": "尚未确认",
    "wind_reduction": "智能降风噪（强度未记录）",
    "wind_reduction_weak": "智能降风噪-弱",
    "wind_reduction_strong": "智能降风噪-强",
    "stereo": "立体声",
    "ambisonic": "全景声 / 360 音频",
    "voice_focus": "人声增强",
}
CAMERA_MICROPHONES = {
    "unknown": "未确认",
    "builtin": "相机内置麦克风",
    "external": "相机外接麦克风",
}
PREPROCESSING = {"off": "关闭额外处理", "lowcut_80hz": "80Hz 低频抑制（实验）"}


class ClassificationFilter:
    """Causal second-order high pass at 16 kHz, continuous across PCM blocks."""

    def __init__(self):
        self.sos = butter(2, 80, btype="highpass", fs=16000, output="sos")
        self.reset()

    def reset(self):
        self.state = np.zeros((len(self.sos), 2), np.float64)

    def process(self, samples):
        output, self.state = sosfilt(self.sos, samples, zi=self.state)
        return output.astype(np.float32)


def classify_views(classifier, reference, processed=None):
    """Preserve baseline scores; a filtered view can add evidence but not veto it.

    This does not guarantee recall on a slower machine or lower false positives.
    Log both score sets for labelled A/B evaluation; disabled by default.
    """
    baseline = classifier.infer(reference)
    enhanced, error = None, None
    if processed is not None:
        try:
            enhanced = classifier.infer(processed)
        except Exception as exc:
            error = str(exc)[:240]
    scores = {k: max(v, enhanced.get(k, 0)) if enhanced else v for k, v in baseline.items()}
    return dict(scores=scores, reference_scores=baseline, processed_scores=enhanced, error=error)


def processing_status(config, source):
    profile = config.get("audio_profile", "unknown")
    microphone = config.get("camera_microphone", "unknown")
    mode = config.get("audio_preprocessing", "off")
    return {
        "camera_profile": profile,
        "camera_profile_label": CAMERA_PROFILES.get(profile, profile),
        "camera_microphone": microphone,
        "camera_microphone_label": CAMERA_MICROPHONES.get(microphone, microphone),
        "camera_profile_applies": source == "camera",
        "local_mode": mode,
        "local_mode_label": PREPROCESSING.get(mode, mode),
        "waveform_basis": "sdk_or_microphone_pcm_before_local_processing",
        "localization_uses_local_filter": False,
        "baseline_guard": mode != "off",
    }
