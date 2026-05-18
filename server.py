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
SCRAPE_TIMEOUT = int(os.environ.get("SCRAPE_TIMEOUT_SECONDS", "60"))
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8099"))
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
LOG_SCRAPED_DATA = os.environ.get("LOG_SCRAPED_DATA", "").lower() in ("1", "true", "yes")

_cache: dict = {"error": "First scrape still pending — please wait."}
_started_at: str = datetime.now(timezone.utc).isoformat()


async def _poll_loop() -> None:
    username = os.environ.get("SONNEN_USERNAME", "")
    password = os.environ.get("SONNEN_PASSWORD", "")

    if not username or not password:
        _log.error("SONNEN_USERNAME / SONNEN_PASSWORD not set — scraper will not run.")
        return

    # Pass credentials via env vars so they don't show up in process lists (ps aux)
    env = os.environ.copy()
    env["SONNEN_USERNAME"] = username
    env["SONNEN_PASSWORD"] = password

    while True:
        _log.info("Starting isolated scrape process...")
        try:
            # Launch scraper as an isolated subprocess
            process = await asyncio.create_subprocess_exec(
                sys.executable, "sonnenbatterie_scraper.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            try:
                # Wait for the process with a timeout
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=SCRAPE_TIMEOUT)
                
                # Stream stderr out to our server's logs
                scraper_stderr = stderr.decode(errors="replace").strip()
                if scraper_stderr:
                    for line in scraper_stderr.splitlines():
                        _log.info("[scraper] %s", line)

                if process.returncode != 0:
                    _log.error("Scraper process failed (exit code %s).", process.returncode)
                    _log.error("--- STDERR ---\n%s", stderr.decode(errors="replace").strip())
                    _log.error("--- STDOUT ---\n%s", stdout.decode(errors="replace").strip())
                    raise RuntimeError(f"Scraper exited with code {process.returncode}")

                # Parse the JSON output printed by sonnenbatterie_scraper.py's CLI
                raw_stdout = stdout.decode(errors="replace").strip()
                try:
                    data = json.loads(raw_stdout)
                except json.JSONDecodeError as e:
                    _log.error("Failed to parse scraper output as JSON. Error: %s", e)
                    _log.error("Raw scraper output:\n%s", raw_stdout)
                    raise RuntimeError("Scraper returned invalid JSON")
                
                _cache.clear()
                _cache.update(data)
                _log.info("Scrape complete. timestamp=%s", _cache.get("timestamp"))
                
                if "error" in data:
                    _log.warning("Scrape returned an internal error: %s", data["error"])
                elif not data.get("battery_info") and not data.get("sonnen_heater"):
                    _log.warning("Scrape returned empty data — both battery_info and sonnen_heater are empty.")
                    
                if LOG_SCRAPED_DATA:
                    _log.info("Scraped data:\n%s", json.dumps(data, indent=2, ensure_ascii=False))

            except asyncio.TimeoutError:
                _log.error("Scrape timed out after %s s — killing subprocess...", SCRAPE_TIMEOUT)
                try:
                    process.terminate()  # Ask Playwright to close cleanly
                    await asyncio.wait_for(process.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    _log.warning("Process ignored SIGTERM, forcing SIGKILL...")
                    process.kill()
                    await process.wait()
                raise TimeoutError(f"Scrape timed out after {SCRAPE_TIMEOUT}s")

        except Exception as exc:
            _log.error("Scrape failed: %s", exc)
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
