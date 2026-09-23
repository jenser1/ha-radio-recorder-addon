# Altlasten (nicht mehr aktiv)

Diese Dateien gehoeren zu einem frueheren Konzept des Add-ons und werden
vom aktuellen Stand **nicht** mehr verwendet. Sie liegen hier nur noch als
Nachschlagewerk und koennen geloescht werden, sobald sie nicht mehr
gebraucht werden.

| Datei | War | Ersetzt durch |
|---|---|---|
| `aufnahme.py`, `aufnahme copy.py` | Eigenstaendiges Skript, Polling-Schleife mit `requests`, Jobs aus `/data/options.json` | `radio_recorder/` (ffmpeg + APScheduler + SQLite) |
| `options.json` | Job-Konfiguration der alten Fassung | Tabelle `jobs` in `/data/radio_recorder.db` |
| `panel_radio_recorder.js`, `radio-recorder.js` | Custom-Panel fuer Home Assistant, las `options.jobs` aus der Add-on-Config | Ingress-Oberflaeche des Add-ons (Sidebar-Panel via `config.yaml`) |
| `lovelace_card.yaml`, `lovelace_radio_recorder.yaml` | Lovelace-Karten fuer dieses Panel | dto. |
| `configuration.yaml.example`, `DASHBOARD_SETUP.md` | Einrichtungsanleitung fuer das Custom-Panel | nicht mehr noetig, das Add-on bringt sein Panel selbst mit |
