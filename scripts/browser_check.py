import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "reports"
    out.mkdir(exist_ok=True)
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 1920, "height": 1080}, device_scale_factor=1
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        await page.goto("http://127.0.0.1:8765")
        await page.wait_for_timeout(4000)
        await page.screenshot(path=str(out / "local-hud-1920.png"))
        await page.get_by_role("button", name="调试视图", exact=True).click()
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(out / "local-debug-1920.png"))
        await page.set_viewport_size({"width": 1366, "height": 768})
        await page.wait_for_timeout(1000)
        await page.screenshot(path=str(out / "local-debug-1366.png"))
        await page.get_by_role("button", name="返回 HUD", exact=True).click()
        await page.screenshot(path=str(out / "local-hud-1366.png"))
        await page.get_by_role("button", name="标定", exact=True).click()
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(out / "local-calibration.png"))
        await page.get_by_role("button", name="关闭面板").click()
        await page.get_by_role("button", name="设置", exact=True).click()
        await page.wait_for_timeout(500)
        assert await page.get_by_role("button", name="保存设置").is_disabled()
        await page.get_by_role("button", name="关闭面板").click()
        overflow = await page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        await browser.close()
    report = {
        "browser_errors": errors,
        "horizontal_overflow": overflow,
        "passed": not errors and not overflow,
    }
    (out / "local-browser.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(report)
    assert report["passed"]


if __name__ == "__main__":
    asyncio.run(main())
