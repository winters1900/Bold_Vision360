# HUD design QA — 2026-09-23

**Findings**

No actionable P0/P1/P2 visual issue remains for the requested directional HUD overlay. The solid three-face prism and separate `^` marker are legible over an actual recorded camera frame; unknown bearing shows no directional marker. The front-right event label no longer crosses the edge ribbon, and the compact unknown-bearing card stays in the bottom portion of a 1366×768 debug view.

**Comparison target and evidence**

- Source visual truth: `design/halo360-hud-concept-v6.png`, 1680×940 pixels.
- Browser-rendered implementation: `reports/local-audio-overlay-recorded-1680.png`, 1680×940 pixels, captured at a 1680×940 CSS viewport with device scale factor 1. The underlying JPEG is from an actual X4 Air recording; the horn event is explicitly marked as a *simulation* for visual QA and does not prove recognition. The local screenshot and recording are ignored by Git.
- Additional rendered states: `reports/local-audio-front-right-simulation.png` for front-right label clearance and `reports/local-audio-unknown-1366-debug.png` for the compact unknown-direction card. Both are local QA artifacts.
- Density normalization: both full-view artifacts are 1680×940 at 1×. No scaling or crop was applied. The implementation's persistent control footer occupies 68 CSS pixels; the concept uses that area for a rendered handlebar. The comparison judges the camera/HUD area above the footer.
- Focused visual inspection at native resolution: rear-left alert region, source approximately x=20–485/y=315–765 and implementation x=45–675/y=510–830; three prism faces, white seams, and the colored `^` remain distinct. Bottom recent-events region, source approximately x=550–1120/y=695–760 and implementation x=615–1065/y=705–770. The smaller live-control density is intentional. A separate crop was unnecessary because both 1× source and implementation were inspected at original resolution.

**Required fidelity surfaces**

| Surface | Result |
| --- | --- |
| Fonts and typography | Chinese labels replace the English concept copy. The danger label remains the largest HUD text near its event; caption and evidence copy are subordinate and readable over the recorded frame. Speech is labelled “人声”, not presented as an unverified transcript. |
| Spacing and layout | Danger content stays at the edge and the center remains open. The recent-events pill occupies the lower center. Forward labels have been moved inside and below the ribbon; the 1366×768 unknown card sits above the bottom pill without overlap. |
| Colors and tokens | P0 uses red-orange, P1 amber, P2 cyan. The prism has opaque gold/red/green faces with white edges and no color-mixing glow; only the separate bearing chevron glows in the event color. Ribbon ends fade. |
| Image quality and assets | The concept's sunset road is illustrative. Product video must come from live camera or labelled replay; the actual 960×480 ERP source is softer than the artwork and cannot be replaced with the concept image. The triangle is rendered as crisp vector geometry because its three opaque faces and rotation are functional state, not a photographic asset. |
| Copy and content | The concept's “Excuse me”, “missed”, and “approaching” claims are omitted unless real transcript or approach evidence exists. Mode and evidence labels remain visible to avoid presenting replay or simulation as live recognition. |

**Comparison history**

1. Initial review found a color-mixing glow on the prism, no separate `^`, an overly long edge arc, a front-right label intersecting the ribbon, and the unknown card too high on a short screen.
2. The prism was rebuilt with opaque colored faces and white seams; a separate colored chevron was added and tied to the bearing relative to viewer yaw. The arc was shortened and tapered, the forward label shifted inward, and height-sensitive bottom placement was restored. `reports/local-audio-overlay-recorded-1680.png`, `reports/local-audio-front-right-simulation.png`, and `reports/local-audio-unknown-1366-debug.png` are the post-fix browser captures.
3. Final browser checks passed at 1920×1080 and 1366×768 in HUD and debug layouts, across eight directions and unknown direction. The 359°→1° marker rotation takes the short path. No browser console errors or horizontal overflow were reported. The 40-case central-area geometry check found at least 87.81% clear area in its 70%-area center rectangle; translucent edge pixels are outside that measurement.

**Intentional differences and remaining validation**

- The UI has a control/status footer and one prominent current alert. This keeps mode, audio source and P0 preemption explicit; the concept displays simultaneous P0 and P2 callouts. A future multi-event treatment requires a separate product decision about divided attention.
- The concept is a staged outdoor scene, while the comparison capture is indoor recorded video with a synthetic event. It validates overlay legibility, not dangerous-sound detection, live camera quality, or field accuracy.
- The edge waveform uses measured PCM energy. Its exact shape will vary with input and is not expected to match the concept artwork. Live sunlight and motion readability remain field checks.

**Implementation checklist**

- [x] Opaque prism faces and independent `^` bearing reinforcement.
- [x] Hide directional reinforcement when bearing is unknown.
- [x] Shortest-path rotation over 0°/360° and forward label clearance.
- [x] Responsive bottom placement and browser/occlusion regression checks.

final result: passed
