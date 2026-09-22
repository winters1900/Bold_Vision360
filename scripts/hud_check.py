"""Validate simulated HUD geometry and priority; explicit simulation never counts as ML accuracy."""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    root = Path(__file__).resolve().parents[1]
    errors = []
    checks = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        await page.goto("http://127.0.0.1:8765")
        await page.wait_for_timeout(1000)
        await page.request.post("http://127.0.0.1:8765/api/start", data={"mode": "simulation"})
        await page.wait_for_timeout(300)
        try:
            for viewport in ({"width": 1920, "height": 1080}, {"width": 1366, "height": 768}):
                await page.set_viewport_size(viewport)
                for angle in range(0, 360, 45):
                    await page.request.post(
                        "http://127.0.0.1:8765/api/simulate",
                        data={"category": "horn", "angle": angle},
                    )
                    await page.wait_for_timeout(150)
                    label = page.locator(".event-label")
                    await label.wait_for()
                    box = await label.bounding_box()
                    assert (
                        box
                        and box["x"] >= 0
                        and box["y"] >= 0
                        and box["x"] + box["width"] <= viewport["width"]
                    )
                    assert box["y"] + box["height"] < viewport["height"] - 68
                checks.append({"viewport": viewport, "eight_sectors_in_bounds": True})
            await page.request.post(
                "http://127.0.0.1:8765/api/simulate", data={"category": "speech", "angle": 45}
            )
            await page.request.post(
                "http://127.0.0.1:8765/api/simulate", data={"category": "horn", "angle": 225}
            )
            await page.wait_for_timeout(200)
            assert "汽车鸣笛" in await page.locator(".event-label").inner_text()
            await page.screenshot(path=str(root / "reports/local-simulation-hud.png"))
            await page.wait_for_timeout(1500)
            assert await page.locator(".event-label").count() == 0
            await page.request.post(
                "http://127.0.0.1:8765/api/simulate", data={"category": "horn", "angle": None}
            )
            await page.wait_for_timeout(200)
            assert await page.locator(".halo").count() == 0
            assert "方向未知" in await page.locator(".unknown-alert").inner_text()
            checks.append(
                {"priority_preemption": True, "expires": True, "unknown_no_direction_arc": True}
            )
            assert not errors, errors
        finally:
            await page.request.post("http://127.0.0.1:8765/api/start", data={"mode": "live"})
            await browser.close()
    report = {
        "passed": True,
        "synthetic_ui_test_only": True,
        "checks": checks,
        "browser_errors": errors,
    }
    (root / "reports/local-hud-tests.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
