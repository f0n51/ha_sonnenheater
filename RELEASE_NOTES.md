# Release Notes

## v1.1.1 — Bugfix

**Released:** 2026-04-28

### Bug fixes

- **Scraper no longer gets stuck on portal downtime or empty responses** ([#2](https://github.com/f0n51/ha_sonnenheater/issues/2)) — added `SCRAPE_TIMEOUT` enforcement via `asyncio.wait_for`; a hung Playwright session is now forcibly cancelled after the configured timeout, the error is written to the cache, and the poll loop continues normally.

## v1.1.0 — Reliability & Reconfiguration

**Released:** 2026-04-15

### Bug fixes

- **Fixed intermittent empty scrape results** — the login form check was instantaneous and could return false on slow SPAs; replaced with `wait_for_selector` (up to 15 s) so the scraper reliably detects the login form before proceeding.

### Improvements

- **Reconfigure without re-adding** — the Home Assistant integration now has a *Configure* button in Settings → Devices & Services. URL and poll interval can be changed at any time; the integration reloads automatically on save.
- **German translations for sensor & reconfiguration UI** — Sensors and Configure dialog strings are fully translated into German (`de.json`).
- **Structured logging with timestamps** — all diagnostic output in `server.py` and `sonnenbatterie_scraper.py` now goes through Python `logging` with ISO timestamps, making Portainer / Docker log output far easier to read.
- **Warnings on empty scrape results** — explicit `WARNING` log entries are emitted when `battery_info` or `sonnen_heater` are empty after a scrape, including which API endpoints (`battery-systems`, `live-state`) were missing.

---

## v1.0.1 — Zuverlässigkeit & Neukonfiguration

**Veröffentlicht:** 2026-04-13

### Fehlerbehebungen

- **Sporadisch leere Scraping-Ergebnisse behoben** — die Prüfung des Login-Formulars erfolgte bisher sofort und konnte bei langsamen SPAs fälschlicherweise „nicht vorhanden" zurückgeben; ersetzt durch `wait_for_selector` (bis zu 15 s), sodass das Login-Formular zuverlässig erkannt wird.

### Verbesserungen

- **Neukonfiguration ohne Neuinstallation** — die Home Assistant Integration hat jetzt einen *Konfigurieren*-Button unter Einstellungen → Geräte & Dienste. URL und Abfrageintervall können jederzeit geändert werden; die Integration lädt sich automatisch neu.
- **Deutsche Übersetzung der Neukonfigurations-Oberfläche** — alle neuen Texte des Konfigurieren-Dialogs sind vollständig auf Deutsch übersetzt (`de.json`).
- **Strukturiertes Logging mit Zeitstempeln** — alle Diagnoseausgaben in `server.py` und `sonnenbatterie_scraper.py` laufen jetzt über Python `logging` mit ISO-Zeitstempeln, was Portainer- und Docker-Logs deutlich lesbarer macht.
- **Warnungen bei leeren Scraping-Ergebnissen** — explizite `WARNING`-Logeinträge werden ausgegeben, wenn `battery_info` oder `sonnen_heater` nach einem Scrape leer sind, inklusive Angabe der fehlenden API-Endpunkte (`battery-systems`, `live-state`).

---

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
