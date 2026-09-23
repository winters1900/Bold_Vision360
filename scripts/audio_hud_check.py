"""Regression checks using recorded PCM and explicitly labelled simulation fixtures.

Does not acquire the camera. Requires the local service; temporarily uses replay,
then stops it. Synthetic events verify rendering only, never localization accuracy.
"""

import asyncio
import copy
import json
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8765"


async def main():
    errors, checks = [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        sessions = await (await page.request.get(URL + "/api/recordings")).json()
        assert sessions, "Record a real audio/video session first"
        session = max(sessions, key=lambda s: s["bytes"])["name"]
        await page.goto(URL)
        try:
            await page.request.post(URL + "/api/start", data={"mode": "replay", "session": session})
            for _ in range(100):
                await page.wait_for_timeout(200)
                state = await (await page.request.get(URL + "/api/status")).json()
                if state["audio_signal"]["observed_ms"] >= 500 and state["fps"] > 0:
                    break
            # Give the 0.96 s model window and debounce time to run on real audio.
            await page.wait_for_timeout(2000)
            state = await (await page.request.get(URL + "/api/status")).json()
            assert state["audio_signal"]["present"], state
            assert len(state["audio_signal"]["envelope"]) > 20
            await page.locator(
                '.signal-wave[data-signal="pcm"], .halo[data-signal="pcm"]'
            ).first.wait_for()
            assert await page.locator(".tetrahedron").count() > 0
            first = await page.locator(".signal-wave path, .wave-ribbon").first.get_attribute("d")
            await page.wait_for_timeout(300)
            second = await page.locator(".signal-wave path, .wave-ribbon").first.get_attribute("d")
            assert first != second, "Measured audio must update the waveform"
            await page.screenshot(path=str(ROOT / "reports/local-audio-replay-1920.png"))
            await page.set_viewport_size({"width": 1366, "height": 768})
            await page.screenshot(path=str(ROOT / "reports/local-audio-replay-1366.png"))
            await page.get_by_role("button", name="调试视图", exact=True).click()
            await page.locator(".audio-diagnostics").scroll_into_view_if_needed()
            await page.screenshot(path=str(ROOT / "reports/local-audio-debug-1366.png"))
            assert not await page.evaluate("document.documentElement.scrollWidth > innerWidth")
            checks.append(
                dict(
                    real_replay=session,
                    changing_pcm_waveform=True,
                    signal=state["audio_signal"],
                    localization=state["localization"],
                )
            )
        finally:
            await page.request.post(URL + "/api/stop")
            await page.close()

        # Isolate controlled UI cases at the browser boundary, labelled simulation.
        fixture = copy.deepcopy(state)
        fixture.update(
            mode="simulation",
            phase="running",
            frame_age_ms=None,
            fps=0,
            audio_source="simulation",
            events=[],
            history=[],
        )
        sockets = []
        page = await browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(ws):
            sockets.append(ws)
            ws.send(json.dumps(fixture))

        await page.route_web_socket("**/ws/events", route)
        await page.route_web_socket("**/ws/frames", lambda ws: None)
        await page.goto(URL)
        await page.wait_for_timeout(400)

        async def push(angle, sector=None, with_signal=True):
            event = dict(
                id="ui-fixture",
                category="horn",
                label="汽车鸣笛",
                priority=0,
                angle=angle,
                sector=sector,
                confidence=0.9,
                evidence="simulation",
                audio_source="simulation",
                created_at=1,
                updated_at=1,
                expires_at=999999,
                approaching=False,
                simulated=True,
                direction_reason="simulation",
                candidate_count=0,
            )
            fixture["events"] = [event]
            fixture["audio_signal"] = (
                state["audio_signal"]
                if with_signal
                else dict(
                    present=False,
                    envelope=[],
                    channel_rms=[],
                    structure="unavailable",
                    correlation=None,
                    difference_ratio=None,
                    level_dbfs=None,
                    observed_ms=0,
                )
            )
            for ws in sockets:
                ws.send(json.dumps(fixture))
            await page.wait_for_timeout(80)

        for width, height in [(1920, 1080), (1366, 768)]:
            await page.set_viewport_size({"width": width, "height": height})
            for debug in (False, True):
                if debug:
                    await page.get_by_role("button", name="调试视图", exact=True).click()
                for angle in range(0, 360, 45):
                    await push(angle, angle // 45)
                    assert await page.locator(".event-label .tetrahedron").count() == 1
                    assert await page.locator(".wave-ribbon").count() == 1
                    hud = await page.locator(".hud-view").bounding_box()
                    box = await page.locator(".event-label").bounding_box()
                    assert (
                        box["x"] >= hud["x"] and box["x"] + box["width"] <= hud["x"] + hud["width"]
                    ), (angle, debug, box, hud)
                    assert (
                        box["y"] >= hud["y"]
                        and box["y"] + box["height"] <= hud["y"] + hud["height"]
                    )
                await push(None)
                assert await page.locator(".halo").count() == 0
                assert await page.locator(".unknown-alert .tetrahedron").count() == 1
                assert (
                    await page.locator('.unknown-alert .signal-wave[data-signal="pcm"]').count()
                    == 1
                )
                assert "方向未知" in await page.locator(".unknown-alert").inner_text()
                await page.screenshot(
                    path=str(
                        ROOT
                        / f"reports/local-audio-unknown-{width}-{'debug' if debug else 'hud'}.png"
                    )
                )
                if debug:
                    await page.get_by_role("button", name="返回 HUD", exact=True).click()
            checks.append(dict(viewport=[width, height], eight_angles_and_unknown=True, debug=True))

        await push(225, 5)
        await page.screenshot(path=str(ROOT / "reports/local-audio-ribbon-simulation.png"))
        await push(35, 0)  # within backend hysteresis: label must stay in the front sector
        assert "前方" in await page.locator(".event-label").inner_text()
        await push(359, 0)
        await page.get_by_title("向左查看").click()
        assert float(await page.locator(".halo").get_attribute("data-angle")) == 44
        assert "右前" in await page.locator(".event-label").inner_text()
        await page.get_by_role("button", name="回正", exact=True).click()
        await push(1, 0)
        assert "前方" in await page.locator(".event-label").inner_text()
        await push(90, 2, with_signal=False)
        assert await page.locator(".wave-ribbon").count() == 0
        assert await page.locator(".event-label .tetrahedron").count() == 1
        fixture["events"] = []
        for ws in sockets:
            ws.send(json.dumps(fixture))
        await page.wait_for_timeout(150)
        assert await page.locator(".halo, .unknown-alert, .event-label").count() == 0
        assert not errors, errors
        await browser.close()
    report = dict(passed=True, synthetic_cases_are_ui_only=True, checks=checks, errors=errors)
    (ROOT / "reports/local-audio-hud-tests.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(dict(passed=True, checks=len(checks), errors=errors)))


if __name__ == "__main__":
    asyncio.run(main())
