import React from "react";

export type SoundEvent = {
  id: string;
  category: string;
  label: string;
  priority: number;
  angle: number | null;
  sector: number | null;
  confidence: number;
  evidence: string;
  audio_source: string;
  created_at: number;
  updated_at: number;
  expires_at: number;
  approaching: boolean;
  simulated: boolean;
  direction_reason?: string;
  candidate_count?: number;
  direction_confidence?: number;
};

export type AudioSignal = {
  present: boolean;
  envelope: number[];
  channel_rms: number[];
  structure: string;
  correlation: number | null;
  difference_ratio: number | null;
  level_dbfs: number | null;
  observed_ms: number;
};

export type Localization = {
  mode: string;
  acoustic_available: boolean;
  title: string;
  detail: string;
};

const colors = ["#ff682f", "#ffc768", "#4fe1dd"];
const directions = [
  "前方",
  "右前",
  "右侧",
  "右后",
  "后方",
  "左后",
  "左侧",
  "左前",
];
const normalize = (v: number) => ((v % 360) + 360) % 360;

export function directionReason(event: SoundEvent) {
  if (event.evidence === "simulation") return "模拟事件 · 不代表真实识别";
  if (event.evidence === "visual_candidate")
    return "视觉候选方向 · 未确认发声目标";
  if (event.evidence === "audio_direction") return "已标定音频方向";
  if (event.evidence === "audio_visual") return "音频方向与视觉目标一致";
  if (event.direction_reason === "ambiguous_audio_categories")
    return "同时识别多类声音 · 方位无法归属";
  if (event.direction_reason === "low_acoustic_confidence")
    return "声学方位置信度不足";
  return event.direction_reason === "multiple_candidates"
    ? `${event.candidate_count} 个匹配目标 · 无法确定声源`
    : "没有唯一匹配的视觉目标";
}

// Three separate faces and visible edges, following the concept's red/green/gold
// tetrahedron. Only verified/candidate bearings rotate it; unknown is an emblem.
export function Tetrahedron({ angle = null }: { angle?: number | null }) {
  return (
    <svg
      className="tetrahedron"
      viewBox="0 0 64 64"
      role="img"
      aria-label={angle === null ? "声音事件图标，方向未知" : "声源方位图标"}
      data-bearing={angle === null ? "unknown" : angle}
      style={{ transform: angle === null ? undefined : `rotate(${angle}deg)` }}
    >
      <g stroke="#fffde9" strokeWidth="1.5" strokeLinejoin="round">
        <path d="M32 4 L59 54 L32 34 Z" fill="#ffc739" />
        <path d="M59 54 L5 54 L32 34 Z" fill="#fb5539" />
        <path d="M5 54 L32 4 L32 34 Z" fill="#79df42" />
      </g>
      <path
        d="M32 4 L32 34 L59 54"
        fill="none"
        stroke="white"
        strokeWidth="1"
      />
    </svg>
  );
}

// Display gain in dBFS, applied to measured 20 ms PCM power buckets. There is no
// oscillator, random animation or category-dependent fabricated waveform.
function levels(signal: AudioSignal | undefined) {
  if (!signal?.present || !signal.envelope.length) return [];
  const values = signal.envelope
    .slice(-64)
    .map((rms) =>
      Math.min(
        1,
        Math.max(0, (20 * Math.log10(Math.max(rms, 1e-6)) + 60) / 45),
      ),
    );
  return [...Array(Math.max(0, 64 - values.length)).fill(0), ...values];
}

export function SignalWave({
  signal,
  className = "",
}: {
  signal?: AudioSignal;
  className?: string;
}) {
  const values = levels(signal);
  const shape = values.length ? values : Array(64).fill(0);
  const top = shape.map((v, i) => `${(i * 300) / 63},${24 - v * 22}`);
  const bottom = [...shape]
    .reverse()
    .map((v, i) => `${((63 - i) * 300) / 63},${24 + v * 22}`);
  return (
    <svg
      className={`signal-wave ${className}`}
      viewBox="0 0 300 48"
      preserveAspectRatio="none"
      role="img"
      aria-label={values.length ? "真实音频能量波形" : "暂无音频波形"}
      data-signal={values.length ? "pcm" : "none"}
    >
      <path
        d={`M${top.join(" L")} L${bottom.join(" L")} Z`}
        fill="currentColor"
        fillOpacity=".28"
      />
      <path
        d={`M${top.join(" L")}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path d="M0 24 H300" stroke="currentColor" opacity=".2" />
    </svg>
  );
}

export function SoundHalo({
  event,
  yaw,
  signal,
}: {
  event: SoundEvent;
  yaw: number;
  signal?: AudioSignal;
}) {
  const angle = event.angle === null ? null : normalize(event.angle - yaw);
  const color = colors[event.priority];
  if (angle === null)
    return (
      <div
        className="unknown-alert"
        style={{ "--alert": color } as React.CSSProperties}
      >
        <div className="unknown-heading">
          <Tetrahedron />
          <div>
            <strong>{event.label}</strong>
            <span>已识别声音 · 方向未知</span>
          </div>
          <b className="sound-priority">P{event.priority}</b>
        </div>
        <SignalWave signal={signal} />
        <small>{directionReason(event)}</small>
      </div>
    );

  const theta = (angle * Math.PI) / 180;
  const values = levels(signal);
  const samples = values.length ? values : Array(64).fill(0);
  const point = (t: number, inset = 0) => [
    500 + (480 - inset) * Math.sin(t),
    300 - (278 - inset) * Math.cos(t),
  ];
  const outer = samples.map((_, i) => point(theta + (i / 63 - 0.5) * 1.75));
  const inner = samples.map((v, i) =>
    point(theta + (i / 63 - 0.5) * 1.75, v * 36 * Math.sin((i / 63) * Math.PI)),
  );
  const path = (p: number[][]) =>
    p.map((v, i) => `${i ? "L" : "M"}${v.join(",")}`).join(" ");
  const ribbon = `${path(outer)} ${path([...inner].reverse()).replace("M", "L")} Z`;
  const x = Math.max(10, Math.min(90, 50 + 43 * Math.sin(theta)));
  const y = Math.max(16, Math.min(77, 50 - 34 * Math.cos(theta)));
  // Respect backend sector hysteresis when rendering the text as well as the arc.
  const sectorAngle = normalize(
    (event.sector === null ? event.angle! : event.sector * 45) - yaw,
  );
  const direction = directions[Math.floor(((sectorAngle + 22.5) % 360) / 45)];
  return (
    <>
      <svg
        className={`halo priority-${event.priority} ${values.length ? "" : "signal-pending"}`}
        viewBox="0 0 1000 600"
        preserveAspectRatio="none"
        aria-hidden="true"
        data-signal={values.length ? "pcm" : "none"}
        data-angle={angle}
        style={{ color }}
      >
        <defs>
          <filter id="sound-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="5" />
          </filter>
        </defs>
        <path
          d={path(outer)}
          stroke="currentColor"
          strokeWidth="12"
          fill="none"
          filter="url(#sound-glow)"
          opacity=".6"
        />
        {values.length > 0 && (
          <>
            <path
              className="wave-ribbon"
              d={ribbon}
              fill="currentColor"
              opacity=".4"
            />
            {outer.map((p, i) => (
              <path
                key={i}
                d={`M${p.join(",")} L${inner[i].join(",")}`}
                stroke="currentColor"
                strokeWidth=".8"
                opacity=".65"
              />
            ))}
            <path
              d={path(inner)}
              stroke="currentColor"
              strokeWidth="1.3"
              fill="none"
            />
          </>
        )}
        <path
          d={path(outer)}
          stroke="currentColor"
          strokeWidth="2.5"
          fill="none"
        />
        <path
          d={path(outer)}
          stroke="#fff6d9"
          strokeWidth=".7"
          fill="none"
          opacity=".9"
        />
      </svg>
      <div
        className="event-label"
        style={
          {
            left: `clamp(154px, ${x}%, calc(100% - 154px))`,
            top: `clamp(170px, ${y}%, calc(100% - 170px))`,
            "--alert": color,
          } as React.CSSProperties
        }
      >
        <div className="event-heading">
          <Tetrahedron angle={angle} />
          <strong>
            {event.label} · {direction}
          </strong>
        </div>
        <span className="event-caption">
          {event.approaching
            ? "目标有接近趋势"
            : event.priority === 0
              ? "注意周围交通"
              : event.priority === 1
                ? "留意周围环境"
                : "附近有人声"}
        </span>
        <small>{directionReason(event)}</small>
      </div>
    </>
  );
}
