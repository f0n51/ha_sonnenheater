"""
Sonnen Scraper REST API Server

Polls my.sonnen.de on a configurable interval and exposes the cached result
at GET /data so that Home Assistant (or anything else) can consume it.

Usage:
    set SONNEN_USERNAME=your@email.com
    set SONNEN_PASSWORD=YourPassword
    python server.py

Optional env vars:
    POLL_INTERVAL_SECONDS   How often to re-scrape (default: 300)
    SERVER_PORT             TCP port to listen on  (default: 8099)
    SERVER_HOST             Bind address           (default: 0.0.0.0)
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from sonnenbatterie_scraper import scrape

_log = logging.getLogger(__name__)

import json

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8099"))
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
LOG_SCRAPED_DATA = os.environ.get("LOG_SCRAPED_DATA", "").lower() in ("1", "true", "yes")

_cache: dict = {"error": "First scrape still pending — please wait."}
_started_at: str = datetime.now(timezone.utc).isoformat()


async def _poll_loop() -> None:
    username = os.environ.get("SONNEN_USERNAME", "")
    password = os.environ.get("SONNEN_PASSWORD", "")

    if not username or not password:
        _log.error(
            "SONNEN_USERNAME / SONNEN_PASSWORD not set — scraper will not run."
        )
        return

    while True:
        _log.info("Starting scrape …")
        try:
            data = await scrape(username, password)
            _cache.clear()
            _cache.update(data)
            _log.info("Scrape complete. timestamp=%s", _cache.get("timestamp"))
            if LOG_SCRAPED_DATA:
                _log.info("Scraped data:\n%s", json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            _log.error("Scrape failed: %s", exc)
            _cache["error"] = str(exc)
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
