"""Einstiegspunkt des Add-ons.

Ablauf beim Start:
 1. Datenbank anlegen bzw. oeffnen (uebernimmt einmalig alte jobs.json)
 2. Aufnahmen fortsetzen, die beim letzten Beenden noch liefen
 3. Zeitplaene in den Scheduler eintragen
 4. Weboberflaeche starten
"""

import os
import signal
import sys

from radio_recorder import __version__, config, db, scheduler, web
from radio_recorder.recorder import recorder


def _prepare_directories():
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        # Kein Abbruch: die Oberflaeche soll erreichbar bleiben, damit der
        # Fehler ueberhaupt sichtbar wird.
        print(f"[start] WARNUNG: Zielordner {config.OUTPUT_DIR} ist nicht "
              f"nutzbar ({err}). Aufnahmen werden fehlschlagen.", flush=True)


def _install_signal_handlers():
    """Beim Stoppen des Add-ons sauber herunterfahren."""

    def _handler(signum, _frame):
        print(f"[start] Signal {signum} empfangen - fahre herunter", flush=True)
        scheduler.shutdown()
        recorder.shutdown()
        # Der Webserver blockiert im Hauptthread; hier hilft nur der harte Weg.
        os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass


def main():
    print(f"[start] Radio Recorder {__version__}", flush=True)
    print(f"[start] Zeitzone: {config.TIMEZONE or 'nicht gesetzt'}", flush=True)
    print(f"[start] Zielordner: {config.OUTPUT_DIR}", flush=True)

    _prepare_directories()
    db.init()

    resumed = recorder.resume_pending()
    if resumed:
        print(f"[start] {resumed} Aufnahme(n) fortgesetzt", flush=True)

    scheduler.start()
    _install_signal_handlers()

    app = web.create_app()
    app.run(host="0.0.0.0", port=config.PORT, threaded=True,
            use_reloader=False)


if __name__ == "__main__":
    sys.exit(main())
