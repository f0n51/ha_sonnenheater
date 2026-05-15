"""
Sonnen Scraper REST API Server

Polls my.sonnen.de on a configurable interval and exposes the cached result
at GET /data so that Home Assistant (or anything else) can consume it.

Usage:
    set SONNEN_USERNAME=your@email.com
    set SONNEN_PASSWORD=YourPassword
    python server.py

Optional env vars:
    POLL_INTERVAL_SECONDS   How often to re-scrape (default: 120)
    SERVER_PORT             TCP port to listen on  (default: 8099)
    SERVER_HOST             Bind address           (default: 0.0.0.0)
"""

import asyncio
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from sonnenbatterie_scraper import scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_log = logging.getLogger(__name__)

import json

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "120"))
SCRAPE_TIMEOUT = int(os.environ.get("SCRAPE_TIMEOUT_SECONDS", "120"))
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8099"))
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
LOG_SCRAPED_DATA = os.environ.get("LOG_SCRAPED_DATA", "").lower() in ("1", "true", "yes")

_cache: dict = {"error": "First scrape still pending — please wait."}
_started_at: str = datetime.now(timezone.utc).isoformat()


def _kill_stale_browsers() -> None:
    """Kill lingering Chromium and Playwright driver processes left by a hung scrape.

    The Playwright Python driver starts a node.js subprocess.  If cleanup is
    interrupted (e.g. by asyncio cancellation), that process keeps running and
    causes subsequent browser launches to hang or fail with
    "BrowserContext.new_page: Target page, context or browser has been closed".

    Safe to call unconditionally; pkill returns non-zero when nothing matches.
    """
    if sys.platform == "win32":
        return  # Not applicable outside Docker/Linux
    for pattern in ("chrome-headless-shell", "playwright/driver/node"):
        try:
            result = subprocess.run(
                ["pkill", "-9", "-f", pattern],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                _log.warning("Killed stale '%s' process(es).", pattern)
        except Exception as exc:  # noqa: BLE001
            _log.debug("pkill '%s': %s", pattern, exc)


async def _poll_loop() -> None:
    username = os.environ.get("SONNEN_USERNAME", "")
    password = os.environ.get("SONNEN_PASSWORD", "")

    if not username or not password:
        _log.error(
            "SONNEN_USERNAME / SONNEN_PASSWORD not set — scraper will not run."
        )
        return

    while True:
        # Ensure no leftover Chromium from a previous hung/incomplete cleanup
        # exists before we try to launch a fresh browser.  This is a no-op on
        # the happy path (pkill returns non-zero when nothing matches).
        _kill_stale_browsers()
        _log.info("Starting scrape …")
        # Create an explicit task so we can manage its lifecycle independently
        # of asyncio.wait_for's cancellation.  asyncio.shield() prevents the
        # wait_for timeout from propagating a CancelledError directly into the
        # task; instead we cancel it ourselves after the timeout and then wait
        # for its finally-block cleanup to finish before pkill-ing any leftovers.
        scrape_task = asyncio.create_task(scrape(username, password))
        try:
            data = await asyncio.wait_for(
                asyncio.shield(scrape_task), timeout=SCRAPE_TIMEOUT
            )
            _cache.clear()
            _cache.update(data)
            _log.info("Scrape complete. timestamp=%s", _cache.get("timestamp"))
            if not data.get("battery_info") and not data.get("sonnen_heater"):
                _log.warning(
                    "Scrape returned empty data — both battery_info and sonnen_heater are empty. "
                    "Captured API URLs may have been missing. Check scraper logs above."
                )
            elif not data.get("battery_info"):
                _log.warning("Scrape returned empty battery_info.")
            elif not data.get("sonnen_heater"):
                _log.warning("Scrape returned empty sonnen_heater.")
            if LOG_SCRAPED_DATA:
                _log.info("Scraped data:\n%s", json.dumps(data, indent=2, ensure_ascii=False))
        except asyncio.TimeoutError:
            _log.error(
                "Scrape timed out after %s s — Playwright likely hung. "
                "Cancelling task and waiting for browser cleanup...",
                SCRAPE_TIMEOUT,
            )
            scrape_task.cancel()
            try:
                # Give the task's finally-block (browser.close + pw.stop) time
                # to finish; the scraper already applies 10 s timeouts on each.
                await asyncio.wait_for(scrape_task, timeout=25)
            except asyncio.TimeoutError:
                _log.warning("Browser cleanup itself timed out — force-killing stale processes.")
            except asyncio.CancelledError:
                pass  # Expected: task accepted the cancellation
            except Exception as cleanup_exc:  # noqa: BLE001
                _log.warning("Cleanup error after timeout: %s", cleanup_exc)
            _kill_stale_browsers()
            _cache.clear()
            _cache["error"] = f"Scrape timed out after {SCRAPE_TIMEOUT}s"
            _cache["timestamp"] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:  # noqa: BLE001
            _log.error("Scrape failed: %s", exc)
            if not scrape_task.done():
                scrape_task.cancel()
                try:
                    await asyncio.wait_for(scrape_task, timeout=25)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass
                _kill_stale_browsers()
            _cache.clear()
            _cache["error"] = str(exc)
            _cache["timestamp"] = datetime.now(timezone.utc).isoformat()
        await asyncio.sleep(POLL_INTERVAL)


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    task = asyncio.create_task(_poll_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Sonnen Scraper API", lifespan=_lifespan)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/data", summary="Return the latest scraped Sonnen data")
async def get_data() -> JSONResponse:
    return JSONResponse(content=_cache)


@app.get("/health", summary="Health check for Docker / load balancers")
async def health() -> JSONResponse:
    healthy = "error" not in _cache
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "last_scrape": _cache.get("timestamp"),
            "started_at": _started_at,
        },
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
