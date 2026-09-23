"""Measure central HUD coverage with isolated simulation fixtures; no camera control.

This is a layout acceptance check, not sound detection or direction accuracy.
Element bounding boxes conservatively count text and card whitespace as covered.
The translucent edge halo is excluded because its SVG bounds span the viewport.
"""

import asyncio
import json
import math
from pathlib import Path

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8765"
OVERLAYS = (
    "header",
    ".heading-scale",
    ".status-strip",
    ".live-metrics",
    ".localization-status",
    ".event-label",
    ".unknown-alert",
    ".audio-monitor",
    ".quiet",
    ".history-bar",
    ".view-controls",
)


def covered_area(rectangles):
    """Exact union of axis-aligned boxes, avoiding double counting overlaps."""
    edges = sorted({x for x0, _, x1, _ in rectangles for x in (x0, x1)})
    area = 0.0
    for left, right in zip(edges, edges[1:]):
        if left == right:
            continue
        spans = sorted((y0, y1) for x0, y0, x1, y1 in rectangles if x0 < right and x1 > left)
        if not spans:
            continue
        low, high = spans[0]
        height = 0.0
        for y0, y1 in spans[1:]:
            if y0 > high:
                height += high - low
                low, high = y0, y1
            else:
                high = max(high, y1)
        height += high - low
        area += (right - left) * height
    return area


def clip_box(box, area):
    x0 = max(box["x"], area[0])
    y0 = max(box["y"], area[1])
    x1 = min(box["x"] + box["width"], area[2])
    y1 = min(box["y"] + box["height"], area[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


async def measure(page):
    hud = await page.locator(".hud-view").bounding_box()
    if not hud:
        raise AssertionError("HUD panel is missing")
    scale = math.sqrt(0.7)
    margin_x = hud["width"] * (1 - scale) / 2
    margin_y = hud["height"] * (1 - scale) / 2
    center = (
        hud["x"] + margin_x,
        hud["y"] + margin_y,
        hud["x"] + hud["width"] - margin_x,
        hud["y"] + hud["height"] - margin_y,
    )
    boxes = []
    for selector in OVERLAYS:
        for element in await page.locator(f".hud-view {selector}").all():
            if await element.is_visible():
                box = await element.bounding_box()
                if box and (clipped := clip_box(box, center)):
                    boxes.append(clipped)
    center_area = (center[2] - center[0]) * (center[3] - center[1])
    return round(1 - covered_area(boxes) / center_area, 4)


async def main():
    errors = []
    cases = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(
            viewport={"width": 1920, "height": 1080}, reduced_motion="reduce"
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        response = await page.request.get(URL + "/api/status")
        assert response.ok, f"status API returned {response.status}"
        fixture = await response.json()
        fixture.update(
            mode="simulation",
            phase="running",
            frame_age_ms=0,
            events=[],
            history=[],
            audio_source="simulation",
        )
        sockets = []

        async def route_events(socket):
            sockets.append(socket)
            socket.send(json.dumps(fixture))

        await page.route_web_socket("**/ws/events", route_events)
        await page.route_web_socket("**/ws/frames", lambda socket: None)
        await page.goto(URL)
        await page.locator(".mode-badge.simulation").wait_for()

        async def show(angle):
            fixture["events"] = (
                []
                if angle == "quiet"
                else [
                    dict(
                        id="layout-fixture",
                        category="horn",
                        label="汽车鸣笛",
                        priority=0,
                        angle=angle,
                        sector=round(angle / 45) if isinstance(angle, int) else None,
                        confidence=0.9,
                        evidence="simulation",
                        audio_source="simulation",
                        created_at=1,
                        updated_at=1,
                        expires_at=fixture["now"] + 10,
                        approaching=False,
                        simulated=True,
                        direction_reason="simulation",
                        candidate_count=0,
                    )
                ]
            )
            for socket in sockets:
                socket.send(json.dumps(fixture))
            if angle == "quiet":
                await page.wait_for_function(
                    "document.querySelectorAll('.event-label, .unknown-alert').length === 0"
                )
            elif angle is None:
                await page.locator(".unknown-alert").wait_for()
            else:
                await page.locator(".event-label").wait_for()

        for width, height in ((1920, 1080), (1366, 768)):
            await page.set_viewport_size({"width": width, "height": height})
            for debug in (False, True):
                if debug:
                    await page.get_by_role("button", name="调试视图", exact=True).click()
                for angle in ("quiet", None, *range(0, 360, 45)):
                    await show(angle)
                    clear = await measure(page)
                    assert clear >= 0.7, (width, height, debug, angle, clear)
                    assert not await page.evaluate(
                        "document.documentElement.scrollWidth > innerWidth"
                    )
                    cases.append(
                        dict(
                            viewport=[width, height],
                            debug=debug,
                            angle=angle,
                            central_clear_fraction=clear,
                        )
                    )
                    if (width, height, debug, angle) == (1366, 768, True, None):
                        await page.screenshot(
                            path=str(ROOT / "reports/local-hud-occlusion-worst.png")
                        )
                if debug:
                    await page.get_by_role("button", name="返回 HUD", exact=True).click()
        assert not errors, errors
        await browser.close()
    report = dict(
        passed=True,
        ui_fixture_only=True,
        central_region_fraction=0.7,
        minimum_clear_fraction=min(case["central_clear_fraction"] for case in cases),
        samples=len(cases),
        scope="HUD text and card bounding boxes; translucent edge halo excluded",
        cases=cases,
        browser_errors=errors,
    )
    output = ROOT / "reports/local-hud-occlusion.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}))


if __name__ == "__main__":
    asyncio.run(main())
