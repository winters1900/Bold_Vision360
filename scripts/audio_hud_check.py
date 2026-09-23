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
        frame_sockets = []
        page = await browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(ws):
            sockets.append(ws)
            ws.send(json.dumps(fixture))

        async def route_frame(ws):
            frame_sockets.append(ws)

        await page.route_web_socket("**/ws/events", route)
        await page.route_web_socket("**/ws/frames", route_frame)
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
                    assert await page.locator(".event-label .bearing-chevron").count() == 1
                    assert await page.locator(".bearing-marker").get_attribute("data-bearing") == str(angle)
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
                assert await page.locator(".bearing-chevron").count() == 0
                assert (
                    await page.locator('.unknown-alert .signal-wave[data-signal="pcm"]').count()
                    == 1
                )
                assert "方向未知" in await page.locator(".unknown-alert").inner_text()
                if height <= 800:
                    hud = await page.locator(".hud-view").bounding_box()
                    card = await page.locator(".unknown-alert").bounding_box()
                    assert hud["y"] + hud["height"] - card["y"] - card["height"] <= 140
                await page.screenshot(
                    path=str(
                        ROOT
                        / f"reports/local-audio-unknown-{width}-{'debug' if debug else 'hud'}.png"
                    )
                )
                if debug:
                    await page.get_by_role("button", name="返回 HUD", exact=True).click()
            checks.append(dict(viewport=[width, height], eight_angles_and_unknown=True, debug=True))

        await page.set_viewport_size({"width": 1680, "height": 940})
        await push(225, 5)
        await page.wait_for_timeout(350)
        marker_rotation = await page.locator(".bearing-marker").evaluate(
            "el => { const m = new DOMMatrixReadOnly(getComputedStyle(el).transform); "
            "return (Math.atan2(m.b, m.a) * 180 / Math.PI + 360) % 360; }"
        )
        assert abs((marker_rotation - 225 + 180) % 360 - 180) < 1
        faces = await page.locator(".event-label .tetrahedron path[fill]").evaluate_all(
            "els => els.map(el => [el.getAttribute('fill'), el.getAttribute('fill-opacity')])"
        )
        assert [face for face in faces if face[0] not in ("#10191c", "none")] == [
            ["#ffc739", "1"],
            ["#fb5539", "1"],
            ["#79df42", "1"],
        ], faces
        assert await page.locator(".event-label .tetrahedron").evaluate(
            "el => getComputedStyle(el).filter"
        ) == "none"
        await page.screenshot(path=str(ROOT / "reports/local-audio-ribbon-simulation.png"))
        # A recorded JPEG tests legibility over moving-camera imagery. The event
        # remains explicitly labelled simulation and never counts as recognition.
        recorded_frame = next((ROOT / "recordings" / session).glob("*.jpg")).read_bytes()
        horn = fixture["events"][0].copy()
        fixture["history"] = [
            dict(horn, updated_at=state["now"] - 3),
            dict(horn, id="ui-voice", category="voice", label="人声", priority=2,
                 angle=35, sector=1, updated_at=state["now"] - 8),
            dict(horn, id="ui-bell", category="bell", label="自行车铃", priority=1,
                 angle=180, sector=4, updated_at=state["now"] - 12),
        ]
        fixture.update(mode="replay", frame_age_ms=0, fps=30)
        for ws in sockets:
            ws.send(json.dumps(fixture))
        for ws in frame_sockets:
            ws.send(recorded_frame)
        await page.locator(".panorama canvas").wait_for()
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(ROOT / "reports/local-audio-overlay-recorded-1680.png"))
        fixture.update(mode="simulation", frame_age_ms=None, fps=0)
        for ws in sockets:
            ws.send(json.dumps(fixture))
        await push(35, 0)  # within backend hysteresis: label must stay in the front sector
        await page.wait_for_timeout(350)
        assert "前方" in await page.locator(".event-label").inner_text()
        await page.screenshot(path=str(ROOT / "reports/local-audio-front-right-simulation.png"))
        await push(359, 0)
        await page.get_by_title("向左查看").click()
        await page.wait_for_timeout(350)
        assert float(await page.locator(".halo").get_attribute("data-angle")) == 44
        assert await page.locator(".bearing-marker").get_attribute("data-bearing") == "44"
        marker_rotation = await page.locator(".bearing-marker").evaluate(
            "el => { const m = new DOMMatrixReadOnly(getComputedStyle(el).transform); "
            "return (Math.atan2(m.b, m.a) * 180 / Math.PI + 360) % 360; }"
        )
        assert abs((marker_rotation - 44 + 180) % 360 - 180) < 1
        assert "右前" in await page.locator(".event-label").inner_text()
        await page.get_by_role("button", name="回正", exact=True).click()
        await page.wait_for_timeout(350)
        await push(1, 0)
        await page.wait_for_timeout(70)
        marker_rotation = await page.locator(".bearing-marker").evaluate(
            "el => { const m = new DOMMatrixReadOnly(getComputedStyle(el).transform); "
            "return (Math.atan2(m.b, m.a) * 180 / Math.PI + 360) % 360; }"
        )
        assert marker_rotation < 30 or marker_rotation > 330, marker_rotation
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
