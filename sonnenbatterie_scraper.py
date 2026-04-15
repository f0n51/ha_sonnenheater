#!/usr/bin/env python3
"""
Sonnen Battery Web Scraper

Authenticates at my.sonnen.de and extracts battery status and
sonnenHeater values from the battery overview page.

Setup:
    pip install -r requirements.txt
    playwright install chromium

Usage:
    python scraper.py -u your@email.com -p YourPassword
    python scraper.py -u your@email.com -p YourPassword --visible   # non-headless
    python scraper.py -u your@email.com -p YourPassword -o data.json

    Or use environment variables:
        set SONNEN_USERNAME=your@email.com
        set SONNEN_PASSWORD=YourPassword
        python scraper.py
"""

import asyncio
import json
import logging
import os
import sys
import argparse
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

_log = logging.getLogger(__name__)

OVERVIEW_URL = "https://my.sonnen.de/battery/overview"





# ---------------------------------------------------------------------------
# Main scraping coroutine
# ---------------------------------------------------------------------------

async def scrape(username: str, password: str, headless: bool = True, debug: bool = False) -> dict:
    """Login to my.sonnen.de and return scraped battery overview data as a dict."""

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            locale="de-DE",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        # Capture JSON API responses for transparency / future use
        api_data: dict = {}

        async def _capture_response(response):
            if response.status == 200 and "sonnen.de" in response.url:
                if "json" in response.headers.get("content-type", ""):
                    try:
                        api_data[response.url] = await response.json()
                    except Exception:
                        pass

        page.on("response", _capture_response)

        try:
            # ── 1. Open page (redirects to login when unauthenticated) ───────
            _log.info("Opening %s ...", OVERVIEW_URL)
            await page.goto(OVERVIEW_URL, wait_until="domcontentloaded", timeout=30_000)
            _log.info("Landed on: %s", page.url)

            # ── 2. Wait for the SPA to render its initial state ──────────────
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeoutError:
                pass  # SPA polls continuously; proceed after timeout

            # ── 3. Login if the login form is now visible ─────────────────────
            # Use wait_for_selector so the SPA has time to render before we decide
            # whether login is needed (instantaneous count() check was too early).
            try:
                await page.wait_for_selector(
                    '[data-testid="login-email"], input[type="email"]',
                    timeout=15_000,
                )
                login_form_visible = True
            except PlaywrightTimeoutError:
                login_form_visible = False  # already authenticated

            login_email = page.locator('[data-testid="login-email"], input[type="email"]')
            if login_form_visible:
                _log.info("Login required — filling credentials ...")

                # Dismiss cookie/consent banner if present
                try:
                    consent = page.locator(
                        "#onetrust-accept-btn-handler, "
                        "button:has-text('Akzeptieren'), "
                        "button:has-text('Accept All')"
                    )
                    if await consent.count() > 0:
                        await consent.first.click()
                        await page.wait_for_timeout(500)
                except Exception:
                    pass

                await login_email.first.fill(username)
                await page.locator(
                    '[data-testid="login-password"], input[type="password"]'
                ).first.fill(password)

                async with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
                    await page.locator(
                        '[data-testid="login-submit-btn"], input[type="submit"], button[type="submit"]'
                    ).first.click()
                _log.info("Credentials submitted — waiting for page to reload ...")
                # SPA polls continuously so networkidle may never fire; wait for load instead
                await page.wait_for_load_state("load", timeout=30_000)

            # ── 4. Navigate to overview if we ended up elsewhere ─────────────
            if "battery/overview" not in page.url:
                await page.goto(OVERVIEW_URL, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_load_state("load", timeout=30_000)

            # ── 5. Wait until the API responses we need have been captured ───────
            _log.info("Waiting for API responses (battery-systems + live-state) ...")
            deadline = asyncio.get_event_loop().time() + 20
            while asyncio.get_event_loop().time() < deadline:
                has_battery = any("battery-systems" in u for u in api_data)
                has_live    = any("live-state" in u for u in api_data)
                if has_battery and has_live:
                    break
                await asyncio.sleep(0.5)
            else:
                captured = list(api_data.keys())
                missing = []
                if not any("battery-systems" in u for u in api_data):
                    missing.append("battery-systems")
                if not any("live-state" in u for u in api_data):
                    missing.append("live-state")
                _log.warning(
                    "Timed out waiting for API data. Missing: %s. Captured URLs: %s",
                    missing, captured
                )

            # ── 6. Debug snapshot ─────────────────────────────────────────────
            if debug:
                html = await page.content()
                with open("debug_page.html", "w", encoding="utf-8") as fh:
                    fh.write(html)
                await page.screenshot(path="debug_screenshot.png", full_page=True)
                _log.debug("Saved debug_page.html and debug_screenshot.png")

            # ── 7. Extract data from captured API responses ───────────────────
            _log.info("Extracting values ... (captured %d API response(s): %s)", len(api_data), list(api_data.keys()))

            battery_systems_data = None
            live_state_data = None
            for url, payload in api_data.items():
                if "battery-systems" in url:
                    battery_systems_data = payload
                if "live-state" in url:
                    live_state_data = payload

            battery_info = {}
            sonnen_heater = {}

            if not battery_systems_data:
                _log.warning("No battery-systems API response captured — battery_info will be empty.")
            if not live_state_data:
                _log.warning("No live-state API response captured — sonnen_heater data will be empty.")

            if battery_systems_data:
                items = battery_systems_data.get("data") or []
                if isinstance(items, list) and items:
                    attrs = items[0].get("attributes", {})
                    battery_info["serial_number"] = attrs.get("serial_number")
                    cap_wh = attrs.get("battery_capacity")
                    battery_info["capacity"] = f"{cap_wh / 1000:.1f} kWh" if cap_wh else None
                    sonnen_heater["max_temperature"] = (
                        f"{attrs['heater_max_temperature']} °C"
                        if attrs.get("heater_max_temperature") is not None else None
                    )
                    # Model from included product resource
                    included = battery_systems_data.get("included") or []
                    for inc in included:
                        if inc.get("type") == "products":
                            p = inc.get("attributes", {})
                            battery_info["model"] = p.get("product_line") or p.get("name")
                            break

            if live_state_data:
                attrs = live_state_data.get("data", {}).get("attributes", {})
                battery_info["operating_mode"] = attrs.get("battery_operating_mode")
                sonnen_heater["power"] = (
                    f"{attrs['heater_power']} W" if attrs.get("heater_power") is not None else None
                )
                sonnen_heater["water_temperature"] = (
                    f"{attrs['heater_water_temp']} °C"
                    if attrs.get("heater_water_temp") is not None else None
                )
                heater_pwr = attrs.get("heater_power")
                if heater_pwr is not None:
                    sonnen_heater["state"] = "active" if heater_pwr > 0 else "inactive"

            battery_info  = {k: v for k, v in battery_info.items()  if v is not None}
            sonnen_heater  = {k: v for k, v in sonnen_heater.items()  if v is not None}

            result = {
                "battery_info":   battery_info,
                "sonnen_heater":  sonnen_heater,
                "timestamp":      datetime.now().isoformat(),
            }

            _log.info("Scrape done. battery_info keys: %s, sonnen_heater keys: %s", list(battery_info.keys()), list(sonnen_heater.keys()))
            return result

        except PlaywrightTimeoutError as exc:
            return {"error": f"Timeout: {exc}", "timestamp": datetime.now().isoformat()}
        except Exception as exc:
            return {"error": str(exc), "timestamp": datetime.now().isoformat()}
        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape battery status and sonnenHeater data from my.sonnen.de",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py -u email@example.com -p MyPassword
  python scraper.py -u email@example.com -p MyPassword --visible
  python scraper.py -u email@example.com -p MyPassword -o data.json

Environment variables (alternative to flags):
  SONNEN_USERNAME   your login email
  SONNEN_PASSWORD   your login password
        """,
    )
    parser.add_argument(
        "--username", "-u", metavar="EMAIL",
        help="Login email (or env var SONNEN_USERNAME)",
    )
    parser.add_argument(
        "--password", "-p", metavar="PASSWORD",
        help="Login password (or env var SONNEN_PASSWORD)",
    )
    parser.add_argument(
        "--output", "-o", metavar="FILE",
        help="Write JSON output to this file (default: stdout)",
    )
    parser.add_argument(
        "--visible", action="store_true",
        help="Show the browser window — useful for debugging login issues",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Save debug_page.html and debug_screenshot.png after rendering",
    )
    args = parser.parse_args()

    username = args.username or os.environ.get("SONNEN_USERNAME", "")
    password = args.password or os.environ.get("SONNEN_PASSWORD", "")

    if not username or not password:
        parser.error(
            "Credentials are required. "
            "Pass --username/-u and --password/-p, "
            "or set SONNEN_USERNAME / SONNEN_PASSWORD environment variables."
        )

    data = asyncio.run(scrape(username, password, headless=not args.visible, debug=args.debug))

    output = json.dumps(data, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(output)
        print(f"Results saved to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
