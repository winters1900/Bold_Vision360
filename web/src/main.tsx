import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import {
  ArrowUpRight,
  ArrowLeft,
  ArrowRight,
  Compass,
  Settings,
  Scan,
  Maximize,
  Minimize,
  Video,
  Mic,
  Activity,
  Radio,
  Play,
  Square,
  RotateCcw,
  X,
  Download,
  ChevronRight,
  Volume2,
  History,
  SlidersHorizontal,
  AlertTriangle,
} from "lucide-react";
import "./style.css";
import {
  SoundHalo as Halo,
  SignalWave,
  Tetrahedron,
  directionReason,
  type SoundEvent,
  type AudioSignal,
  type Localization,
} from "./audio-hud";

type Alert = SoundEvent;
type Target = {
  label: string;
  bbox: number[];
  angle: number;
  confidence: number;
  track_id: number;
};
type State = {
  mode: string;
  phase: string;
  error: string | null;
  now: number;
  frame_id: number;
  frame_age_ms: number | null;
  fps: number;
  audio_source: string;
  channels: number;
  audio_rate: number;
  energy: number;
  audio_signal?: AudioSignal;
  localization?: Localization;
  audio_processing?: {
    camera_profile_label: string;
    camera_microphone_label: string;
    camera_profile_applies: boolean;
    local_mode: string;
    local_mode_label: string;
    baseline_guard: boolean;
  };
  audio_comparison?: {
    reference_scores: Record<string, number>;
    processed_scores: Record<string, number> | null;
    error: string | null;
  };
  scores: Record<string, number>;
  models: Record<string, string>;
  native: Record<string, any>;
  targets: Target[];
  events: Alert[];
  history: Alert[];
  recording: string | null;
  detection_ms: number;
  audio_inference_ms: number;
  calibration: any;
  calibration_stage: number | string | null;
  calibration_captured: number[];
  calibration_error?: string | null;
  calibration_quality?: {
    passed: boolean;
    reason: string;
    failed_angles: number[];
    max_error_deg: number | null;
  };
  forward_offset_deg: number;
  clock_diagnostics: any;
};
const initial: State = {
  mode: "idle",
  phase: "stopped",
  error: null,
  now: 0,
  frame_id: 0,
  frame_age_ms: null,
  fps: 0,
  audio_source: "none",
  channels: 0,
  audio_rate: 0,
  energy: 0,
  scores: {},
  models: {},
  native: {},
  targets: [],
  events: [],
  history: [],
  recording: null,
  detection_ms: 0,
  audio_inference_ms: 0,
  calibration: null,
  calibration_stage: null,
  calibration_captured: [],
  forward_offset_deg: 0,
  clock_diagnostics: {},
};
const dirs = ["前方", "右前", "右侧", "右后", "后方", "左后", "左侧", "左前"];
const colors = ["#ff622f", "#ffc768", "#4fe1dd"];
const source: Record<string, string> = {
  camera: "X4 Air 麦克风",
  microphone: "电脑麦克风",
  none: "等待音频",
  simulation: "模拟输入",
};
const labels: Record<string, string> = {
  horn: "汽车鸣笛",
  siren: "警笛",
  bell: "自行车铃",
  shout: "喊声",
  speech: "人声",
  brake: "轮胎尖叫/打滑声",
  crash: "碰撞/碎裂声",
  vehicle_passing: "车辆经过",
  dog_bark: "犬吠",
  doorbell: "门铃",
};
const normalize = (a: number) => ((a % 360) + 360) % 360;
const direction = (a: number | null) =>
  a === null
    ? "方向未知"
    : dirs[Math.floor(((normalize(a) + 22.5) % 360) / 45)];
async function api(path: string, body?: unknown) {
  const r = await fetch("/api/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}

function Panorama({
  bitmap,
  yaw,
  forward,
  flat = false,
}: {
  bitmap: ImageBitmap | null;
  yaw: number;
  forward: number;
  flat?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null),
    state = useRef<{
      renderer: THREE.WebGLRenderer;
      material: THREE.ShaderMaterial;
      texture: THREE.CanvasTexture;
      canvas: HTMLCanvasElement;
    } | null>(null);
  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const canvas = document.createElement("canvas");
    canvas.width = 960;
    canvas.height = 480;
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = THREE.RepeatWrapping;
    const material = new THREE.ShaderMaterial({
      uniforms: {
        map: { value: texture },
        yaw: { value: 0 },
        aspect: { value: 1 },
        isFlat: { value: flat ? 1 : 0 },
      },
      vertexShader:
        "varying vec2 vUv; void main(){vUv=uv;gl_Position=vec4(position.xy,0.,1.);}",
      fragmentShader: `uniform sampler2D map;uniform float yaw;uniform float aspect;uniform int isFlat;varying vec2 vUv;void main(){vec2 uv=vUv;if(isFlat==0){vec2 p=(vUv*2.-1.)*vec2(1.,1./aspect);float a=atan(p.x)+yaw;float e=atan(p.y,sqrt(1.+p.x*p.x));uv=vec2(.5+a/6.2831853,.5+e/3.14159265);}gl_FragColor=texture2D(map,uv);
#include <colorspace_fragment>
}`,
    });
    const scene = new THREE.Scene();
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
    scene.add(mesh);
    const camera = new THREE.Camera();
    const observer = new ResizeObserver(() => {
      renderer.setSize(el.clientWidth, el.clientHeight);
      material.uniforms.aspect.value =
        el.clientWidth / Math.max(1, el.clientHeight);
    });
    observer.observe(el);
    renderer.setAnimationLoop(() => renderer.render(scene, camera));
    state.current = { renderer, material, texture, canvas };
    return () => {
      observer.disconnect();
      renderer.setAnimationLoop(null);
      renderer.dispose();
      texture.dispose();
      material.dispose();
      mesh.geometry.dispose();
      el.replaceChildren();
      state.current = null;
    };
  }, [flat]);
  useEffect(() => {
    if (state.current)
      state.current.material.uniforms.yaw.value =
        ((yaw + forward) * Math.PI) / 180;
  }, [yaw, forward]);
  useEffect(() => {
    const s = state.current;
    if (!s || !bitmap) return;
    s.canvas.width = bitmap.width;
    s.canvas.height = bitmap.height;
    s.canvas.getContext("2d")!.drawImage(bitmap, 0, 0);
    s.texture.needsUpdate = true;
  }, [bitmap]);
  return <div className={"panorama " + (flat ? "flat" : "")} ref={host} />;
}

function App() {
  const [s, setS] = useState(initial),
    [connected, setConnected] = useState(false),
    [bitmap, setBitmap] = useState<ImageBitmap | null>(null),
    [debug, setDebug] = useState(false),
    [yaw, setYaw] = useState(0),
    [panel, setPanel] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [selected, setSelected] = useState<Alert | null>(null),
    [sessions, setSessions] = useState<{ name: string; bytes: number }[]>([]),
    [config, setConfig] = useState<any>(null),
    [microphones, setMicrophones] = useState<any[]>([]),
    [fullscreen, setFullscreen] = useState(false),
    [simCategory, setSimCategory] = useState("horn"),
    [simAngle, setSimAngle] = useState(225);
  const oldBitmap = useRef<ImageBitmap | null>(null),
    alive = useRef(true);
  const action = async (fn: () => Promise<any>) => {
    setBusy(true);
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setNotice(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    alive.current = true;
    let stateSocket: WebSocket, frameSocket: WebSocket;
    let timer: ReturnType<typeof setTimeout>;
    let frameTimer: ReturnType<typeof setTimeout>;
    let decoding = false;
    const events = () => {
      stateSocket = new WebSocket(`ws://${location.host}/ws/events`);
      stateSocket.onopen = () => setConnected(true);
      stateSocket.onmessage = (e) => setS(JSON.parse(e.data));
      stateSocket.onclose = () => {
        setConnected(false);
        if (alive.current) timer = setTimeout(events, 1500);
      };
    };
    const frames = () => {
      frameSocket = new WebSocket(`ws://${location.host}/ws/frames`);
      frameSocket.binaryType = "blob";
      frameSocket.onmessage = async (e) => {
        if (decoding) return;
        decoding = true;
        try {
          const next = await createImageBitmap(e.data);
          if (!alive.current) {
            next.close();
            return;
          }
          const previous = oldBitmap.current;
          oldBitmap.current = next;
          setBitmap(next);
          setTimeout(() => previous?.close(), 100);
        } finally {
          decoding = false;
        }
      };
      frameSocket.onclose = () => {
        if (alive.current) frameTimer = setTimeout(frames, 1500);
      };
    };
    events();
    frames();
    const full = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", full);
    return () => {
      alive.current = false;
      clearTimeout(timer);
      clearTimeout(frameTimer);
      stateSocket?.close();
      frameSocket?.close();
      oldBitmap.current?.close();
      document.removeEventListener("fullscreenchange", full);
    };
  }, []);
  useEffect(() => {
    if (s.mode === "idle" || s.mode === "simulation") setBitmap(null);
  }, [s.mode]);
  useEffect(() => {
    if (panel === "replay")
      fetch("/api/recordings")
        .then((r) => r.json())
        .then(setSessions);
    if (panel === "settings") {
      fetch("/api/config")
        .then((r) => r.json())
        .then(setConfig);
      fetch("/api/microphones")
        .then((r) => r.json())
        .then(setMicrophones)
        .catch(() => {});
    }
  }, [panel]);
  const live =
    connected &&
    s.frame_age_ms !== null &&
    s.frame_age_ms < 2000 &&
    s.mode !== "idle";
  const primary = s.events[0],
    modeLabel =
      s.mode === "live"
        ? "实时"
        : s.mode === "replay"
          ? "录制回放"
          : s.mode === "simulation"
            ? "模拟演示"
            : "待连接";
  const phaseLabels: Record<string, string> = {
    stopped: "准备连接设备",
    starting: "正在启动",
    connecting: "正在连接 X4 Air",
    running: "环境感知运行中",
    retrying: "正在恢复相机会话",
    error: "连接需要检查",
    ended: "回放已结束",
  };
  const start = () => action(() => api("start", { mode: "live" }));
  const full = () =>
    document.fullscreenElement
      ? document.exitFullscreen()
      : document.documentElement.requestFullscreen();
  return (
    <main className={debug ? "app debug" : "app"}>
      <div className="view-layout">
        {debug && (
          <section className="erp-view">
            <div className="view-title">
              <Scan size={15} /> 360° 环境视图 <span>ERP / 960 × 480</span>
            </div>
            <div className="erp-image">
              {bitmap && live ? (
                <Panorama bitmap={bitmap} yaw={0} forward={0} flat />
              ) : (
                <div className="no-frame">等待全景画面</div>
              )}
              {live &&
                s.targets.map((t) =>
                  [-1, 0, 1].map((shift) => (
                    <div
                      key={t.track_id + ":" + shift}
                      className="bbox"
                      style={{
                        left: (t.bbox[0] + shift) * 100 + "%",
                        top: t.bbox[1] * 100 + "%",
                        width: t.bbox[2] * 100 + "%",
                        height: t.bbox[3] * 100 + "%",
                      }}
                    >
                      <span>
                        {t.label} {Math.round(t.confidence * 100)}%
                      </span>
                    </div>
                  )),
                )}
            </div>
            <div className="debug-stats">
              <div>
                <span>视频</span>
                <strong>
                  {s.fps.toFixed(1)}
                  <small> FPS</small>
                </strong>
              </div>
              <div>
                <span>检测耗时</span>
                <strong>
                  {s.detection_ms}
                  <small> ms</small>
                </strong>
              </div>
              <div>
                <span>声音推理</span>
                <strong>
                  {s.audio_inference_ms}
                  <small> ms</small>
                </strong>
              </div>
            </div>
            <div className="classifications">
              <h3>
                声音分类 <span>最近窗口 · 模型分数</span>
              </h3>
              {Object.entries(labels).map(([k, v]) => (
                <div className="score" key={k}>
                  <span>{v}</span>
                  <i>
                    <b style={{ width: (s.scores[k] || 0) * 100 + "%" }} />
                  </i>
                  <small>{(s.scores[k] || 0).toFixed(2)}</small>
                </div>
              ))}
              <p>
                {source[s.audio_source]} · {s.channels} 声道 /{" "}
                {s.audio_rate || "—"} Hz
              </p>
              <p>音频模型：{s.models.audio || "等待服务"}</p>
              <p>视觉模型：{s.models.vision || "等待服务"}</p>
              <div className="audio-diagnostics">
                <h3>
                  收音与定位{" "}
                  <span>{s.audio_signal?.level_dbfs ?? "—"} dBFS</span>
                </h3>
                <SignalWave signal={s.audio_signal} />
                <strong>{s.localization?.title || "等待音频诊断"}</strong>
                <p>{s.localization?.detail}</p>
                <p>
                  {s.audio_processing?.camera_profile_applies
                    ? `${s.audio_processing.camera_microphone_label} · ${s.audio_processing.camera_profile_label}`
                    : "当前输入未使用相机收音模式"}
                </p>
                <p>
                  软件降噪：
                  {s.audio_processing?.local_mode_label || "关闭额外处理"}
                </p>
                {s.audio_processing?.baseline_guard && (
                  <p>
                    分类同时参考相机输出与低频抑制结果；波形、录制和定位使用软件处理前的音频。
                  </p>
                )}
                {s.audio_comparison?.error && (
                  <p className="processing-error">
                    额外分类处理不可用，已保留基线：{s.audio_comparison.error}
                  </p>
                )}
                {s.audio_signal?.correlation !== null &&
                  s.audio_signal?.correlation !== undefined && (
                    <p>
                      声道相关性 {s.audio_signal.correlation.toFixed(5)} ·
                      差异能量比{" "}
                      {s.audio_signal.difference_ratio?.toExponential(2)}
                    </p>
                  )}
              </div>
            </div>
          </section>
        )}
        <section className={"hud-view " + (!live ? "inactive" : "")}>
          {bitmap && live && (
            <Panorama
              bitmap={bitmap}
              yaw={yaw}
              forward={s.forward_offset_deg}
            />
          )}
          <div className="vignette" />
          {!live && (
            <div className="empty-state">
              <div className="orbit">
                <span />
                <Compass size={42} strokeWidth={1} />
              </div>
              <div className="eyebrow">SEE THE SOUND. SENSE THE WORLD.</div>
              <h1>
                {s.mode === "simulation"
                  ? "让方向，变得可见。"
                  : s.mode === "replay"
                    ? "重温每一次感知。"
                    : "看见声音的方向。"}
              </h1>
              <p>
                {s.mode === "simulation"
                  ? "当前为模拟模式，事件由控制面板注入。"
                  : s.mode === "replay"
                    ? "选择录制会话，重放画面与原始声音。"
                    : "连接 X4 Air，让 360° 环境声音成为清晰的视觉提示。"}
              </p>
              {s.mode === "idle" && (
                <button
                  className="primary"
                  onClick={start}
                  disabled={busy || !connected}
                >
                  <Video size={17} />
                  连接相机 <ArrowUpRight size={17} />
                </button>
              )}
              {s.mode !== "idle" && (
                <span className="phase-message">{phaseLabels[s.phase]}</span>
              )}
            </div>
          )}
          <header>
            <a className="brand" href="/" aria-label="Bold Vision 360">
              <span className="brand-icon">
                <Radio size={22} />
              </span>
              <div>
                BOLD VISION<span>360 / 环境感知</span>
              </div>
            </a>
            <div className={"mode-badge " + s.mode}>
              <i />
              {modeLabel}
              {s.mode === "simulation" && " · 非真实识别"}
            </div>
            <button className="icon-button" aria-label="全屏" onClick={full}>
              {fullscreen ? <Minimize size={18} /> : <Maximize size={18} />}
            </button>
          </header>
          <div className="heading-scale">
            <span>左</span>
            <i />
            <b>{direction(yaw)}</b>
            <i />
            <span>右</span>
          </div>
          <div className="status-strip">
            <span className={"status-dot " + (live ? "good" : "")} />
            {live ? "360° 感知已连接" : phaseLabels[s.phase]}
            <em />
            {source[s.audio_source]}
          </div>
          <div className="live-metrics">
            <span>
              <Video size={13} />
              {s.fps.toFixed(0)} FPS
            </span>
            <span>
              <Mic size={13} />
              {s.audio_source === "none" ? "—" : s.channels + " CH"}
            </span>
          </div>
          {(live || s.mode === "simulation") && primary && (
            <Halo event={primary} yaw={yaw} signal={s.audio_signal} />
          )}
          {live &&
          !primary &&
          s.audio_signal?.present &&
          (s.audio_signal.level_dbfs ?? -120) > -60 ? (
            <div className="audio-monitor">
              <Tetrahedron />
              <div>
                <span>
                  {s.models.audio?.startsWith("ready")
                    ? "正在分析环境声音"
                    : "已收到环境声音"}
                </span>
                <SignalWave signal={s.audio_signal} />
                <small>
                  {source[s.audio_source]} ·{" "}
                  {s.models.audio?.startsWith("error")
                    ? "分类模型不可用"
                    : s.models.audio?.startsWith("ready")
                      ? "尚未确认类别"
                      : "分类模型加载中"}
                </small>
              </div>
            </div>
          ) : (
            (live || s.mode === "simulation") &&
            !primary && (
              <div className="quiet">
                <span />
                留意前方，感知交给我们
              </div>
            )
          )}
          {live && (
            <button
              className="localization-status"
              onClick={() => setPanel("calibration")}
              title={s.localization?.detail}
            >
              <Compass size={13} />
              {s.localization?.title || "正在检查定位能力"}
              <ChevronRight size={12} />
            </button>
          )}
          <div className="history-bar">
            <div className="history-title">
              <History size={14} />
              <span>最近事件</span>
            </div>
            {s.history.slice(0, 3).map((e) => (
              <button
                key={e.id}
                className="history-item"
                onClick={() => setSelected(e)}
                style={{ "--alert": colors[e.priority] } as React.CSSProperties}
              >
                {e.angle === null ? (
                  <Volume2 size={21} />
                ) : (
                  <ArrowUpRight
                    size={21}
                    style={{ transform: `rotate(${e.angle - 45}deg)` }}
                  />
                )}
                <span>
                  {e.label}
                  <small>
                    {Math.max(0, Math.floor(s.now - e.updated_at))} 秒前 ·{" "}
                    {direction(e.angle)}
                  </small>
                </span>
              </button>
            ))}
            {!s.history.length && (
              <span className="history-empty">暂无事件，保持专注</span>
            )}
          </div>
          <div className="view-controls">
            <button
              title="向左查看"
              onClick={() => setYaw(normalize(yaw - 45))}
            >
              <ArrowLeft size={15} />
            </button>
            <button onClick={() => setYaw(0)}>
              <Compass size={14} />
              回正
            </button>
            <button
              title="向右查看"
              onClick={() => setYaw(normalize(yaw + 45))}
            >
              <ArrowRight size={15} />
            </button>
          </div>
        </section>
      </div>
      <footer>
        <div className="footer-brand">
          <span className={connected ? "connected" : ""} />
          {connected ? "本地服务在线" : "正在连接本地服务"}
          <small>ON-DEVICE AI</small>
        </div>
        <nav>
          <button
            className={debug ? "active" : ""}
            onClick={() => setDebug(!debug)}
          >
            <SlidersHorizontal size={16} />
            {debug ? "返回 HUD" : "调试视图"}
          </button>
          <button onClick={() => setPanel("replay")}>
            <History size={16} />
            回放
          </button>
          <button onClick={() => setPanel("calibration")}>
            <Compass size={16} />
            标定
          </button>
          <button onClick={() => setPanel("settings")}>
            <Settings size={16} />
            设置
          </button>
        </nav>
        <div className="session-controls">
          {s.mode !== "idle" ? (
            <>
              <button
                className={s.recording ? "record recording" : "record"}
                onClick={() =>
                  action(() =>
                    api(s.recording ? "record/stop" : "record/start"),
                  )
                }
                disabled={s.mode !== "live" || s.phase !== "running"}
              >
                <i />
                {s.recording ? "录制中" : "录制"}
              </button>
              <button
                className="stop"
                onClick={() => action(() => api("stop"))}
                disabled={busy}
              >
                <Square size={13} />
                停止
              </button>
            </>
          ) : (
            <button
              className="connect"
              onClick={start}
              disabled={busy || !connected}
            >
              <Play size={14} />
              连接相机
            </button>
          )}
        </div>
      </footer>
      {(notice || s.error || !connected) && (
        <div className="toast">
          <AlertTriangle size={17} />
          <span>
            {notice || s.error || "本地服务连接中，请确认启动脚本仍在运行。"}
          </span>
          {notice && (
            <button aria-label="关闭提示" onClick={() => setNotice("")}>
              <X size={14} />
            </button>
          )}
        </div>
      )}
      {panel && (
        <div className="modal-backdrop" onClick={() => setPanel(null)}>
          <section className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-heading">
              <div>
                <span className="eyebrow">BOLD VISION / CONTROL</span>
                <h2>
                  {panel === "replay"
                    ? "录制与回放"
                    : panel === "calibration"
                      ? "让方向对齐真实世界"
                      : "系统设置"}
                </h2>
              </div>
              <button
                className="icon-button"
                aria-label="关闭面板"
                onClick={() => setPanel(null)}
              >
                <X />
              </button>
            </div>
            {panel === "replay" && (
              <>
                <p>回放保留原始音视频时间关系，并重新运行本地识别。</p>
                <div className="session-list">
                  {sessions.map((v) => (
                    <button
                      key={v.name}
                      onClick={() =>
                        action(async () => {
                          await api("start", {
                            mode: "replay",
                            session: v.name,
                          });
                          setPanel(null);
                        })
                      }
                    >
                      <div>
                        <Video />
                        <span>
                          {v.name}
                          <small>
                            {(v.bytes / 1048576).toFixed(1)} MB · 本地录制
                          </small>
                        </span>
                      </div>
                      <Play size={18} />
                    </button>
                  ))}
                  {!sessions.length && (
                    <div className="empty-card">
                      还没有录制会话。连接相机后，点击底部“录制”。
                    </div>
                  )}
                </div>
                <h3>界面验证</h3>
                <p>模拟模式仅用于验证告警样式，不代表真实识别结果。</p>
                <button
                  className="secondary"
                  onClick={() =>
                    action(() => api("start", { mode: "simulation" }))
                  }
                >
                  进入模拟模式
                </button>
                {s.mode === "simulation" && (
                  <div className="simulation-controls">
                    <select
                      value={simCategory}
                      onChange={(e) => setSimCategory(e.target.value)}
                    >
                      {Object.entries(labels).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                    <select
                      value={simAngle}
                      onChange={(e) => setSimAngle(Number(e.target.value))}
                    >
                      <option value={-1}>方向未知</option>
                      {dirs.map((d, i) => (
                        <option key={d} value={i * 45}>
                          {d}
                        </option>
                      ))}
                    </select>
                    <button
                      className="primary"
                      onClick={() =>
                        action(async () => {
                          await api("simulate", {
                            category: simCategory,
                            angle: simAngle < 0 ? null : simAngle,
                          });
                          setPanel(null);
                        })
                      }
                    >
                      发送事件
                    </button>
                  </div>
                )}
              </>
            )}
            {panel === "calibration" && (
              <>
                <p>
                  先将相机朝向佩戴者正前方。仅在相机输出四声道、声道排列和转动测试均通过后启用声源方向。
                </p>
                <div className="capability">
                  <Mic />
                  <div>
                    <strong>
                      {source[s.audio_source]} · {s.channels} 声道
                    </strong>
                    <span>{s.localization?.title || "声源方向尚未验证"}</span>
                  </div>
                </div>
                <p className="localization-detail">{s.localization?.detail}</p>
                {s.audio_processing?.camera_profile_applies && (
                  <p>
                    当前记录：{s.audio_processing.camera_microphone_label} ·{" "}
                    {s.audio_processing.camera_profile_label}
                    （机身设置由用户确认）
                  </p>
                )}
                <a
                  className="diagnostic-download"
                  href="/api/audio/diagnostics"
                  download
                >
                  <Download size={14} />
                  导出声音诊断
                </a>
                {s.channels === 2 && (
                  <div className="audio-help">
                    <strong>当前实时音频无法完成四方位标定</strong>
                    <p>
                      可先停止取流，在相机屏幕顶部下拉 →
                      音频设置，核对收音模式；重新连接后，本页会自动检查实际声道。
                    </p>
                    <p>
                      “360 音频”用于全景视频录制，不保证 SDK
                      直播输出空间声道。选择设置不会直接启用定位，仍以收到的数据和标定结果为准。
                    </p>
                  </div>
                )}
                <ol className="instructions">
                  <li>在设置中填写相机机身实际收音模式。</li>
                  <li>
                    声源距相机约 1.5m，在对应位置持续发声；每次采样 2 秒。
                  </li>
                  <li>
                    完成四方位后，先把声源移回最初的正前方并固定；相机从上往下看顺时针转
                    90°，此时声源应位于相机新的左侧。继续发声并验证。
                  </li>
                </ol>
                <div className="calibration-grid">
                  {[0, 90, 180, 270].map((a) => (
                    <button
                      disabled={
                        busy ||
                        s.calibration_stage !== null ||
                        s.mode !== "live" ||
                        s.channels !== 4 ||
                        s.audio_source !== "camera"
                      }
                      className={
                        s.calibration_captured.includes(a) ? "captured" : ""
                      }
                      key={a}
                      onClick={() =>
                        action(() => api("calibration/capture", { angle: a }))
                      }
                    >
                      <Compass
                        size={20}
                        style={{ transform: `rotate(${a}deg)` }}
                      />
                      {direction(a)}
                      <small>
                        {s.calibration_captured.includes(a)
                          ? "已采样"
                          : "采样 2 秒"}
                      </small>
                    </button>
                  ))}
                </div>
                {s.calibration_error && (
                  <p role="alert" className="localization-detail">
                    标定未通过：{s.calibration_error}
                    。已保存的采样会保留，可重采对应方位。
                  </p>
                )}
                {s.calibration?.estimates && (
                  <div className="audio-help">
                    <strong>
                      {s.calibration_quality?.passed
                        ? "逐方位与转动门槛已满足"
                        : s.calibration.rotation_verified
                          ? "声道映射已验证 · 方位精度未通过"
                          : "声道映射拟合完成 · 等待验证"}
                    </strong>
                    <p>{s.calibration_quality?.reason}</p>
                    <p>
                      拟合平均误差 {s.calibration.mean_error_deg.toFixed(1)}° ·
                      最大误差 {s.calibration.max_error_deg.toFixed(1)}°
                    </p>
                    <p>
                      {s.calibration.estimates
                        .map(
                          (v: { target: number; error_deg: number }) =>
                            `${direction(v.target)} ${v.error_deg.toFixed(1)}°`,
                        )
                        .join(" · ")}
                    </p>
                    {s.calibration.rotation && (
                      <p>
                        转动测试：预期 270°，测得{" "}
                        {s.calibration.rotation.measured.toFixed(1)}°，误差{" "}
                        {s.calibration.rotation.error_deg.toFixed(1)}°。
                      </p>
                    )}
                    <p>
                      采样已保存。以上为本次标定结果，完整现场精度验收尚未完成。
                    </p>
                  </div>
                )}
                <button
                  className="primary"
                  disabled={
                    busy ||
                    s.calibration_stage !== null ||
                    s.mode !== "live" ||
                    s.channels !== 4 ||
                    s.audio_source !== "camera" ||
                    !s.calibration
                  }
                  onClick={() =>
                    action(() =>
                      api("calibration/capture", { angle: "rotation" }),
                    )
                  }
                >
                  {busy ? "正在采样…" : "验证相机向右转 90°"}
                </button>
                <button
                  className="text-button"
                  onClick={() => action(() => api("calibration/reset"))}
                >
                  <RotateCcw size={14} />
                  重新标定
                </button>
                <p className="muted">
                  单/双声道仍可识别声音类别。没有可靠证据时，系统显示“方向未知”。
                </p>
              </>
            )}
            {panel === "settings" && config && (
              <>
                <p>修改前请停止采集。设备与模型均在本机运行。</p>
                <label>
                  前方偏移角 <span>{config.forward_offset_deg}°</span>
                  <input
                    type="range"
                    min="-180"
                    max="180"
                    step="1"
                    value={config.forward_offset_deg}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        forward_offset_deg: Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  相机收音设备（按机身实际情况记录）
                  <select
                    value={config.camera_microphone ?? "unknown"}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        camera_microphone: e.target.value,
                      })
                    }
                  >
                    <option value="unknown">尚未确认</option>
                    <option value="builtin">相机内置麦克风</option>
                    <option value="external">相机外接麦克风</option>
                  </select>
                </label>
                <label>
                  相机机身收音模式
                  <select
                    value={config.audio_profile}
                    onChange={(e) =>
                      setConfig({ ...config, audio_profile: e.target.value })
                    }
                  >
                    <option value="unknown">尚未确认</option>
                    <option value="ambisonic">全景声 / 360 音频</option>
                    <option value="stereo">立体声</option>
                    <option value="wind_reduction_weak">智能降风噪-弱</option>
                    <option value="wind_reduction_strong">智能降风噪-强</option>
                    <option value="voice_focus">人声增强</option>
                    <option value="wind_reduction">
                      智能降风噪（旧记录，强度未确认）
                    </option>
                  </select>
                </label>
                <p className="muted">
                  以上两项用于记录机身状态，不会遥控相机切换模式。降噪模式与是否具备方向能力分别验证。
                </p>
                <label>
                  软件降噪（仅声音分类）
                  <select
                    value={config.audio_preprocessing ?? "off"}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        audio_preprocessing: e.target.value,
                      })
                    }
                  >
                    <option value="off">关闭额外处理（默认）</option>
                    <option value="lowcut_80hz">80Hz 低频抑制（实验）</option>
                  </select>
                </label>
                <p className="muted">
                  低频抑制只处理分类副本，并保留未额外处理的分类结果。它不能消除所有风噪，尚未验证能提高危险声音召回率；机身已开强降风噪时，默认不叠加。
                </p>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={config.microphone_fallback}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        microphone_fallback: e.target.checked,
                      })
                    }
                  />
                  相机无音频时使用电脑麦克风
                </label>
                <label>
                  备用输入设备
                  <select
                    value={config.microphone_device ?? ""}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        microphone_device:
                          e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                  >
                    <option value="">系统默认麦克风</option>
                    {microphones.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="primary"
                  disabled={busy || s.mode !== "idle"}
                  onClick={() =>
                    action(async () => {
                      await api("config", config);
                      setNotice("设置已保存");
                    })
                  }
                >
                  保存设置
                </button>
                <div className="model-info">
                  <h3>运行状态</h3>
                  <p>视觉：{s.models.vision || "加载中"}</p>
                  <p>声音：{s.models.audio || "加载中"}</p>
                  <p>相机：{s.native.serial || "未连接"}</p>
                  <a href="/api/events/export" download>
                    <Download size={15} />
                    导出事件 JSONL
                  </a>
                </div>
              </>
            )}
          </section>
        </div>
      )}
      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <section
            className="event-detail"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="icon-button close"
              aria-label="关闭事件"
              onClick={() => setSelected(null)}
            >
              <X />
            </button>
            <span className="eyebrow">EVENT / {selected.id}</span>
            <h2 style={{ color: colors[selected.priority] }}>
              {selected.label} · {direction(selected.angle)}
            </h2>
            <p>{directionReason(selected)}</p>
            <dl>
              <dt>来源</dt>
              <dd>{source[selected.audio_source]}</dd>
              <dt>优先级</dt>
              <dd>P{selected.priority}</dd>
              <dt>声音模型分数</dt>
              <dd>{selected.confidence.toFixed(2)}</dd>
              <dt>接近趋势</dt>
              <dd>{selected.approaching ? "视觉目标增大" : "未确认"}</dd>
            </dl>
          </section>
        </div>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
