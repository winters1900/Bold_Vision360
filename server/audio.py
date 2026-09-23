import csv
from collections import deque
import itertools
import math
from pathlib import Path
import numpy as np
from scipy.signal import butter, resample_poly, sosfilt
from .domain import delta
from .noise import ClassificationFilter, PREPROCESSING


def pcm_from_frame(frame):
    """Preserve every decoded channel; never upmix mono for display or localization."""
    pcm = frame.to_ndarray()
    channels = len(frame.layout.channels)
    pcm = pcm.T if frame.format.is_planar else pcm.reshape(-1, channels)
    if np.issubdtype(pcm.dtype, np.integer):
        info = np.iinfo(pcm.dtype)
        midpoint = (info.max + 1) / 2 if info.min == 0 else 0
        pcm = (pcm.astype(np.float32) - midpoint) / (midpoint or -info.min)
    return np.ascontiguousarray(pcm, dtype=np.float32)


class AudioSignal:
    """Real 20 ms RMS envelope and measured channel capability, independent of ML.

    A stereo AAC label does not prove independent microphones. Require a 0.5 s
    window with non-silent overall energy before reporting duplicated channels.
    No inferred bearing.
    """

    def __init__(self):
        self.clear()

    def clear(self):
        self.envelope = deque(maxlen=64)
        self.blocks = deque()
        self.pending = np.empty(0, dtype=np.float32)
        self.signature = None
        self.last_time = None

    def append(self, pcm, rate, source, timestamp):
        signature = (source, rate, pcm.shape[1])
        if signature != self.signature or (
            self.last_time is not None and not 0 <= timestamp - self.last_time <= 0.35
        ):
            self.clear()
        self.signature = signature
        self.last_time = timestamp
        p = np.nan_to_num(pcm.astype(np.float64), nan=0, posinf=0, neginf=0)
        # Keep per-channel power, including antiphase audio that a mono mix cancels.
        power = np.mean(p * p, axis=1)
        self.pending = np.concatenate((self.pending, power))
        step = max(1, round(rate * 0.02))
        count = len(self.pending) // step
        if count:
            levels = np.sqrt(self.pending[: count * step].reshape(count, step).mean(axis=1))
            self.envelope.extend(float(v) for v in levels)
            self.pending = self.pending[count * step :]
        self.blocks.append((timestamp, len(p), p.sum(axis=0), p.T @ p))
        while self.blocks and timestamp - self.blocks[0][0] > 1:
            self.blocks.popleft()

    def snapshot(self, now):
        empty = dict(
            present=False,
            envelope=[],
            channel_rms=[],
            structure="unavailable",
            correlation=None,
            difference_ratio=None,
            level_dbfs=None,
            observed_ms=0,
        )
        if not self.blocks or self.last_time is None or now - self.last_time > 1:
            return empty
        n = sum(b[1] for b in self.blocks)
        sums = sum(b[2] for b in self.blocks)
        products = sum(b[3] for b in self.blocks)
        covariance = products / n - np.outer(sums / n, sums / n)
        channel_rms = np.sqrt(np.maximum(0, np.diag(products) / n))
        level = float(np.sqrt(np.mean(channel_rms**2)))
        duration = n / self.signature[1]
        channels = self.signature[2]
        structure = "analyzing"
        correlation = difference = None
        if level < 1e-4:
            structure = "quiet"
        elif duration >= 0.5:
            if channels == 1:
                structure = "mono"
            elif channels == 2:
                denominator = float(products[0, 0] + products[1, 1])
                difference = max(0.0, float(denominator - 2 * products[0, 1])) / max(
                    denominator, 1e-20
                )
                correlation = float(
                    np.clip(
                        covariance[0, 1]
                        / max(np.sqrt(max(0.0, covariance[0, 0] * covariance[1, 1])), 1e-20),
                        -1,
                        1,
                    )
                )
                structure = "dual_mono" if difference < 1e-6 else "stereo_unverified"
            else:
                structure = "multichannel_unverified"
        return dict(
            present=True,
            envelope=list(self.envelope),
            channel_rms=channel_rms.tolist(),
            structure=structure,
            correlation=correlation,
            difference_ratio=difference,
            level_dbfs=round(20 * math.log10(max(level, 1e-6)), 1),
            observed_ms=round(duration * 1000),
        )


def localization_status(signal, source, channels, calibrated=False):
    if not signal["present"]:
        return dict(
            mode="unavailable",
            acoustic_available=False,
            title="等待音频",
            detail="尚无有效音频，无法判断声源方向。",
        )
    if source == "camera" and channels == 4 and calibrated:
        return dict(
            mode="acoustic",
            acoustic_available=True,
            title="声源方向已标定",
            detail="四方位与转动验证已通过；低置信度时仍显示方向未知。",
        )
    structure = signal["structure"]
    descriptions = {
        "dual_mono": (
            "双声道同源 · 仅视觉候选",
            "两路音频几乎相同，当前输入无法独立定位。唯一、类别匹配的视觉目标可提供候选方向。",
        ),
        "mono": ("单声道 · 仅视觉候选", "单声道用于声音分类，方向需由唯一匹配的视觉目标提供。"),
        "stereo_unverified": (
            "双声道 · 仅视觉候选",
            "检测到声道差异，但未验证空间映射；当前仅使用唯一匹配视觉目标的候选方向。",
        ),
        "multichannel_unverified": (
            "多声道 · 待标定",
            "声道数不代表空间音频；须通过四方位与转动验证才能启用声源方向。",
        ),
        "quiet": ("声音较轻 · 仅视觉候选", "当前声音不足以判断声道结构；声音分类仍在运行。"),
        "analyzing": ("正在检查声道", "收集至少半秒有效声音后检查声道结构。"),
    }
    title, detail = descriptions.get(structure, descriptions["analyzing"])
    return dict(mode="visual_candidate_only", acoustic_available=False, title=title, detail=detail)


GROUPS = {
    "horn": ["Vehicle horn, car horn, honking", "Air horn, truck horn"],
    "siren": [
        "Siren",
        "Civil defense siren",
        "Police car (siren)",
        "Ambulance (siren)",
        "Fire engine, fire truck (siren)",
    ],
    "bell": ["Bicycle bell"],
    "shout": ["Shout", "Yell", "Screaming"],
    "speech": ["Speech", "Conversation"],
    # Map only acoustically specific AudioSet labels to HUD events. Broad
    # labels such as Vehicle, Animal and Noise are too ambiguous for alerts.
    "brake": ["Tire squeal", "Skidding"],
    "crash": ["Smash, crash", "Breaking", "Shatter"],
    "vehicle_passing": ["Car passing by"],
    "dog_bark": ["Bark", "Bow-wow"],
    "doorbell": ["Doorbell", "Ding-dong"],
}


class Classifier:
    def __init__(self, root: Path):
        import tensorflow as tf

        tf.config.threading.set_intra_op_parallelism_threads(2)
        tf.config.threading.set_inter_op_parallelism_threads(2)
        self.model = tf.saved_model.load(str(root))
        with open(root / "assets" / "yamnet_class_map.csv", encoding="utf-8") as f:
            labels = [row["display_name"] for row in csv.DictReader(f)]
        self.indices = {
            k: [i for i, v in enumerate(labels) if v in names] for k, names in GROUPS.items()
        }
        missing = [name for name, indices in self.indices.items() if not indices]
        if missing:
            raise ValueError(f"YAMNet 分类标签缺失: {', '.join(missing)}")
        self.model(np.zeros(16000, dtype=np.float32))

    def infer(self, mono):
        scores = self.model(mono.astype(np.float32))[0].numpy().mean(axis=0)
        return {k: float(max(scores[idx])) if idx else 0 for k, idx in self.indices.items()}


class AudioWindow:
    def __init__(self):
        self.filter = ClassificationFilter()
        self.clear()

    def clear(self):
        self.samples = np.empty(0, dtype=np.float32)
        self.processed_samples = np.empty(0, dtype=np.float32)
        self.preprocessing = "off"
        self.format = None
        self.filter.reset()
        self.source = None
        self.last_time = None
        self.last_infer = 0

    def append(self, pcm, rate, source, timestamp, preprocessing="off", mono_channel=None):
        if preprocessing not in PREPROCESSING:
            raise ValueError("不支持的音频预处理")
        signature = (rate, pcm.shape[1], preprocessing, mono_channel)
        if (
            source != self.source
            or signature != self.format
            or (self.last_time is not None and not 0 <= timestamp - self.last_time <= 0.35)
        ):
            self.clear()
        self.format = signature
        self.preprocessing = preprocessing
        self.source = source
        self.last_time = timestamp
        # A verified Ambisonic W channel is omnidirectional. Averaging W/X/Y/Z
        # can cancel a source; unverified formats keep the ordinary downmix.
        mono = pcm.mean(axis=1) if mono_channel is None else pcm[:, mono_channel]
        g = math.gcd(rate, 16000)
        out = resample_poly(mono, 16000 // g, rate // g).astype(np.float32)
        self.samples = np.concatenate([self.samples, out])[-16000:]
        if preprocessing == "lowcut_80hz":
            processed = self.filter.process(out)
            self.processed_samples = np.concatenate([self.processed_samples, processed])[-16000:]
        return float(np.sqrt(np.mean(mono**2)))

    def ready(self, now):
        return len(self.samples) >= 15600 and now - self.last_infer >= 0.1


SPATIAL_METHOD = "shared_band_80_4000_v1"


def spatial_covariance(pcm, rate):
    """Identical fixed band on all channels, never independent channel denoising.

    Keep source PCM untouched. Calibration, rotation and live 300 ms estimates
    all use this path. The band is fixed, not optimized against labelled angles.
    Discard 20 ms of filter startup in each independent analysis window.
    """
    if rate < 16000 or pcm.ndim != 2 or pcm.shape[1] != 4:
        raise ValueError("定位需要至少 16kHz 的四声道音频")
    if len(pcm) < rate // 10 or not np.isfinite(pcm).all():
        raise ValueError("定位音频过短或包含无效数值")
    p = pcm.astype(np.float64)
    p -= p.mean(axis=0)
    p = sosfilt(butter(2, [80, 4000], btype="bandpass", fs=rate, output="sos"), p, axis=0)
    return np.cov(p[round(rate * 0.02) :], rowvar=False, bias=True)


def covariance_intensity(covariance, mapping):
    w, x, y = (mapping[k] for k in ("w", "x", "y"))
    ix = float(covariance[w, x]) * mapping["sx"]
    iy = float(covariance[w, y]) * mapping["sy"]
    energy = float(covariance[w, w] + covariance[x, x] + covariance[y, y])
    if energy < 3e-8:
        return 0.0, 0.0
    confidence = min(1.0, 2 * math.hypot(ix, iy) / max(energy, 1e-12))
    return math.degrees(math.atan2(iy, ix)) % 360, confidence


def intensity(pcm, mapping, rate=48000):
    return covariance_intensity(spatial_covariance(pcm, rate), mapping)


def fit_axes(samples, rate=48000):
    """Four labelled captures; accept only a unique consistent directional mapping."""
    if set(samples) != {0, 90, 180, 270}:
        raise ValueError("需要前、右、后、左四段采样")
    covariances = {a: spatial_covariance(pcm, rate) for a, pcm in samples.items()}
    candidates = []
    for w, x, y in itertools.permutations(range(4), 3):
        for sx, sy in itertools.product((-1, 1), repeat=2):
            mapping = dict(w=w, x=x, y=y, sx=sx, sy=sy)
            estimates = [
                (target, *covariance_intensity(cov, mapping)) for target, cov in covariances.items()
            ]
            error = float(np.mean([abs(delta(a, t)) for t, a, _ in estimates]))
            minimum = min(c for _, _, c in estimates)
            candidates.append((error, minimum, mapping, estimates))
    candidates = [item for item in candidates if item[1] >= 0.2]
    if not candidates:
        raise ValueError("声场置信度过低，无法确认方向")
    candidates.sort(key=lambda item: item[0])
    best = candidates[0]
    if best[0] > 22.5 or best[1] < 0.2:
        raise ValueError("方向误差或声场置信度未达标，请在安静环境重新采样")
    if len(candidates) > 1 and candidates[1][0] - best[0] < 5:
        raise ValueError("声道映射不唯一，不能确认 Ambisonic；请重新采样")
    return {
        "method": SPATIAL_METHOD,
        "sample_rate": rate,
        "channels": 4,
        "mapping": best[2],
        "mean_error_deg": best[0],
        "median_error_deg": float(np.median([abs(delta(a, t)) for t, a, _ in best[3]])),
        "max_error_deg": max(abs(delta(a, t)) for t, a, _ in best[3]),
        "minimum_confidence": best[1],
        "mapping_gap_deg": candidates[1][0] - best[0] if len(candidates) > 1 else None,
        "estimates": [
            dict(target=t, measured=a, error_deg=abs(delta(a, t)), confidence=c)
            for t, a, c in best[3]
        ],
        "rotation_verified": False,
    }
