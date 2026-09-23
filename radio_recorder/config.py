"""Zentrale Konfiguration.

Die Werte stammen aus den Add-on-Optionen und werden von ``run.sh`` als
Umgebungsvariablen gesetzt. Beim lokalen Testen greifen die Vorgabewerte.
"""

import os
from pathlib import Path

__all__ = [
    "OUTPUT_DIR", "DATA_DIR", "WORK_DIR", "DB_FILE", "LEGACY_JOBS_FILE",
    "TIMEZONE", "DEFAULT_DURATION_HOURS", "DEFAULT_DURATION_MINUTES",
    "SEGMENT_MINUTES", "MAX_DURATION_MINUTES", "PORT", "STATIONS",
    "MAX_STREAM_RETRIES", "RETRY_BACKOFF_SECONDS", "SHUTDOWN_TIMEOUT",
    "FFMPEG", "MIN_FREE_MB", "SPACE_CHECK_SECONDS", "DEFAULT_BITRATE_KBPS",
    "get_station", "station_choices",
]


def _int_env(name, default, minimum=None, maximum=None):
    """Liest eine ganze Zahl aus der Umgebung und faengt Unsinn ab."""
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except (AttributeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _path_env(name, default):
    raw = (os.environ.get(name) or "").strip()
    return Path(raw or default)


# --- Pfade ---------------------------------------------------------------

# Zielordner fuer die fertigen Aufnahmen (Add-on-Option "output_dir").
OUTPUT_DIR = _path_env("OUTPUT_DIR", "/media/Musick/Radioaufnahmen")

# Persistenter Add-on-Speicher. Ueberlebt Updates und Neustarts.
DATA_DIR = _path_env("DATA_DIR", "/data")

# Arbeitsverzeichnis fuer angefangene Aufnahmen (Segmente).
#
# Vorgabe ist der Add-on-Speicher. Der liegt lokal und uebersteht damit auch
# einen Netzwerkausfall, waehrend eine Aufnahme laeuft. Wer wenig Platz auf
# dem Systemdatentraeger hat, kann ihn ueber die Option "work_dir" auf eine
# andere Ablage legen - dann aber ohne diesen Schutz.
_work_override = (os.environ.get("WORK_DIR") or "").strip()
WORK_DIR = Path(_work_override) if _work_override else DATA_DIR / "work"

DB_FILE = DATA_DIR / "radio_recorder.db"

# Zeitplaene der Version 0.2.0. Werden einmalig in die Datenbank uebernommen.
LEGACY_JOBS_FILE = DATA_DIR / "jobs.json"


# --- Zeit ----------------------------------------------------------------

# Von run.sh aus der Home-Assistant-Systemkonfiguration gesetzt. Ohne diesen
# Wert liefe der Scheduler in UTC und alle Zeitplaene waeren verschoben.
TIMEZONE = (os.environ.get("TZ") or "").strip() or None


# --- Aufnahme ------------------------------------------------------------

DEFAULT_DURATION_HOURS = _int_env("DEFAULT_DURATION_HOURS", 4, 0, 24)
DEFAULT_DURATION_MINUTES = _int_env("DEFAULT_DURATION_MINUTES", 0, 0, 59)

# Eine laufende Aufnahme wird in Haeppchen dieser Laenge geschrieben. Bricht
# das Add-on ab, ist hoechstens das angefangene Haeppchen betroffen; alles
# davor bleibt heil und wird am Ende zusammengefuegt.
SEGMENT_MINUTES = _int_env("SEGMENT_MINUTES", 10, 1, 60)

MAX_DURATION_MINUTES = 24 * 60

# So viel Platz soll auf dem Datentraeger frei bleiben. Wird vor dem Start
# geprueft und waehrend langer Aufnahmen ueberwacht.
MIN_FREE_MB = _int_env("MIN_FREE_MB", 500, 0, 1024 * 1024)

# Abstand zwischen zwei Platzpruefungen waehrend einer laufenden Aufnahme.
SPACE_CHECK_SECONDS = 60

# Bricht der Stream mitten in der Aufnahme weg, versucht es das Add-on so oft
# erneut, solange die geplante Endzeit noch nicht erreicht ist.
MAX_STREAM_RETRIES = 10
RETRY_BACKOFF_SECONDS = 15

# Wie lange beim Herunterfahren auf ffmpeg gewartet wird, damit das
# angefangene Segment noch sauber geschlossen werden kann.
SHUTDOWN_TIMEOUT = 20

PORT = _int_env("PORT", 8099)

# Aufrufbefehl fuer ffmpeg, als Liste. Dadurch laesst sich in Tests ein
# Platzhalter einsetzen, ohne den Aufnahmecode anzufassen.
FFMPEG = ["ffmpeg"]


# --- Sender --------------------------------------------------------------
# Phase 1 ersetzt diese feste Liste durch verwaltbare Sender in der Datenbank.

STATIONS = {
    "sunshine_live": {
        "name": "SUNSHINE LIVE",
        "url": "https://stream.sunshine-live.de/live/mp3-192/stream.sunshine-live.de/",
        "ext": "mp3",
        # Nur zur Abschaetzung des Platzbedarfs, nicht fuer die Aufnahme selbst.
        "bitrate_kbps": 192,
    },
}

DEFAULT_BITRATE_KBPS = 192


def get_station(key):
    """Liefert die Senderdaten oder loest ``ValueError`` aus."""
    try:
        return STATIONS[key]
    except KeyError:
        raise ValueError(f"Unbekannter Sender: {key!r}") from None


def station_choices():
    """Sender als Liste fuer Auswahlfelder."""
    return [(key, st["name"]) for key, st in STATIONS.items()]
