# Release Notes

## v1.0.0 — Initial Release

**Released:** 2026-04-09

### What's new

- **Home Assistant custom integration** (`custom_components/sonnenheater`) — installs via HACS, adds a *Sonnen Heater* device with four entities:
  - Heater Power (W)
  - Heater Water Temperature (°C)
  - Heater Max Temperature (°C)
  - Heater State (`active` / `inactive`)
- **REST API server** (`server.py`) — long-running FastAPI service that scrapes the sonnen Customer Portal on a configurable interval and caches the result so Home Assistant can poll without spawning a new browser session each time.
- **CLI scraper** (`sonnenbatterie_scraper.py`) — one-shot tool that prints or saves scraped data as JSON.
- **Docker support** — pre-built image published to `ghcr.io/f0n51/ha_sonnenheater:latest`; `docker-compose.yml` included for easy deployment.
- Credentials are never stored; passed via environment variables or CLI flags only.

### Requirements

- Home Assistant 2025.5.0+
- A running instance of the REST API server reachable from Home Assistant
