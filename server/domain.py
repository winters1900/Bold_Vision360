"""Head-relative geometry and evidence-based alerts; no model/runtime dependencies."""

from collections import deque
from dataclasses import asdict, dataclass, field
import math
import time
import uuid

LABELS = {
    "horn": "汽车鸣笛",
    "siren": "警笛",
    "bell": "自行车铃",
    "shout": "喊声",
    "speech": "人声",
    "brake": "轮胎尖叫/打滑声",
    "crash": "碰撞/碎裂声",
    "vehicle_passing": "车辆经过",
    "dog_bark": "犬吠",
    "doorbell": "门铃",
}
PRIORITY = {
    "horn": 0,
    "siren": 0,
    "bell": 1,
    "shout": 1,
    "brake": 1,
    "crash": 1,
    "speech": 2,
    "vehicle_passing": 2,
    "dog_bark": 2,
    "doorbell": 2,
}
DEFAULT_THRESHOLDS = {
    "horn": 0.35,
    "siren": 0.35,
    "bell": 0.35,
    "shout": 0.4,
    "speech": 0.55,
    "brake": 0.5,
    "crash": 0.55,
    "vehicle_passing": 0.6,
    "dog_bark": 0.6,
    "doorbell": 0.55,
}
DIRECTIONS = ["前方", "右前", "右侧", "右后", "后方", "左后", "左侧", "左前"]
MATCHES = {
    "horn": {"car", "truck", "bus", "motorcycle"},
    "siren": {"car", "truck", "bus"},
    "bell": {"bicycle"},
    "shout": {"person"},
    "speech": {"person"},
    "brake": {"car", "truck", "bus", "motorcycle"},
    "crash": set(),
    "vehicle_passing": {"car", "truck", "bus"},
    "dog_bark": set(),
    "doorbell": set(),
}


def acoustic_bearing_unambiguous(categories):
    """One FOA intensity vector cannot assign bearings to distinct sound types.

    YAMNet may label the same voice as both speech and shout, so they share a
    family. Other concurrent category hits keep their alerts but lose the
    acoustic bearing; a unique visual candidate may still supply its own.
    """
    families = {"voice" if name in ("speech", "shout") else name for name in categories}
    return len(families) == 1


def delta(a, b):
    return (a - b + 180) % 360 - 180


def sector(angle):
    return int((angle + 22.5) % 360 // 45)


class DirectionFilter:
    def __init__(self):
        self.samples = deque()
        self.current = None

    def update(self, angle, now):
        self.samples.append((now, angle))
        while self.samples and now - self.samples[0][0] > 0.3:
            self.samples.popleft()
        x = sum(math.cos(math.radians(a)) for _, a in self.samples)
        y = sum(math.sin(math.radians(a)) for _, a in self.samples)
        smooth = math.degrees(math.atan2(y, x)) % 360
        if self.current is None or abs(delta(smooth, self.current * 45)) > 37.5:
            self.current = sector(smooth)
        return smooth, self.current


@dataclass
class Event:
    id: str
    category: str
    label: str
    priority: int
    angle: float | None
    sector: int | None
    confidence: float
    evidence: str
    audio_source: str
    created_at: float
    updated_at: float
    expires_at: float
    approaching: bool = False
    simulated: bool = False
    direction_reason: str = ""
    candidate_count: int = 0
    target_id: int | None = None
    direction_confidence: float = 0
    # Host monotonic clock when fusion created this version of the event.
    # updated_at is the timestamp of the most recent contributing input block.
    generated_at: float = field(default_factory=time.perf_counter)


class Fusion:
    def __init__(self):
        self.events = {}
        self.history = deque(maxlen=100)
        self.filters = {}

    def clear(self):
        self.events.clear()
        self.filters.clear()

    def observe(
        self,
        category,
        confidence,
        now,
        targets,
        audio_source,
        angle=None,
        direction_confidence=0,
        simulated=False,
        unknown_reason=None,
    ):
        candidates = [
            t
            for t in targets
            if t["label"] in MATCHES[category] and abs(now - t["timestamp"]) < 0.5
        ]
        evidence = "audio_only"
        target = None
        if angle is not None and direction_confidence >= 0.2:
            evidence = "audio_direction"
            associated = [t for t in candidates if abs(delta(t["angle"], angle)) < 25]
            if len(associated) == 1:
                evidence, target = "audio_visual", associated[0]
        else:
            angle = None
            if len(candidates) == 1:
                target = candidates[0]
                angle, evidence = target["angle"], "visual_candidate"
        if simulated:
            evidence = "simulation"
        direction_reason = {
            "audio_only": "multiple_candidates"
            if len(candidates) > 1
            else (unknown_reason or "no_candidate"),
            "visual_candidate": "unique_visual_candidate",
            "audio_direction": "calibrated_audio",
            "audio_visual": "audio_visual_match",
            "simulation": "simulation",
        }[evidence]
        old = self.events.get(category)
        if old and old.expires_at < now:
            old = None
            self.filters.pop(category, None)
        target_id = target.get("track_id") if target else None
        # An unknown direction or a different candidate starts a fresh bearing.
        # Blending unrelated candidates creates an angle supported by neither.
        if angle is None or (old and (old.evidence != evidence or old.target_id != target_id)):
            self.filters.pop(category, None)
        band = None
        if angle is not None:
            angle, band = self.filters.setdefault(category, DirectionFilter()).update(angle, now)
        event = Event(
            old.id if old else uuid.uuid4().hex[:12],
            category,
            LABELS[category],
            PRIORITY[category],
            angle,
            band,
            float(confidence),
            evidence,
            audio_source,
            old.created_at if old else now,
            now,
            now + 1.2,
            bool(target and target.get("approaching")),
            simulated,
            direction_reason,
            len(candidates),
            target_id,
            float(direction_confidence) if evidence in ("audio_direction", "audio_visual") else 0,
        )
        self.events[category] = event
        if not old:
            self.history.appendleft(event)
        else:
            for i, previous in enumerate(self.history):
                if previous.id == event.id:
                    self.history[i] = event
                    break
        return event

    def snapshot(self, now):
        active = [e for e in self.events.values() if e.expires_at > now]
        active.sort(key=lambda e: (e.priority, -e.updated_at))
        # Only highest-priority event occupies the HUD. Others remain in history.
        return [asdict(e) for e in active[:1]], [asdict(e) for e in list(self.history)[:30]]
