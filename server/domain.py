"""Head-relative geometry and evidence-based alerts; no model/runtime dependencies."""
from collections import deque
from dataclasses import asdict, dataclass
import math
import uuid

LABELS = {"horn": "汽车鸣笛", "siren": "警笛", "bell": "自行车铃", "shout": "喊声", "speech": "人声"}
PRIORITY = {"horn": 0, "siren": 0, "bell": 1, "shout": 1, "speech": 2}
DIRECTIONS = ["前方", "右前", "右侧", "右后", "后方", "左后", "左侧", "左前"]
MATCHES = {"horn": {"car", "truck", "bus", "motorcycle"}, "siren": {"car", "truck", "bus"},
           "bell": {"bicycle"}, "shout": {"person"}, "speech": {"person"}}

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
        while self.samples and now - self.samples[0][0] > .3:
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

class Fusion:
    def __init__(self):
        self.events = {}
        self.history = deque(maxlen=100)
        self.filters = {}

    def clear(self):
        self.events.clear()
        self.filters.clear()

    def observe(self, category, confidence, now, targets, audio_source, angle=None, direction_confidence=0, simulated=False):
        candidates = [t for t in targets if t["label"] in MATCHES[category] and abs(now-t["timestamp"]) < .5]
        evidence = "audio_only"
        target = None
        if angle is not None and direction_confidence >= .2:
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
        old = self.events.get(category)
        if old and old.expires_at < now:
            old = None
            self.filters.pop(category, None)
        band = None
        if angle is not None:
            angle, band = self.filters.setdefault(category, DirectionFilter()).update(angle, now)
        event = Event(old.id if old else uuid.uuid4().hex[:12], category, LABELS[category], PRIORITY[category],
                      angle, band, float(confidence), evidence, audio_source, old.created_at if old else now,
                      now, now+1.2, bool(target and target.get("approaching")), simulated)
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
