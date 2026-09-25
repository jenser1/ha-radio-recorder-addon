"""Vorhandene Aufnahmen im Zielordner aufspueren.

Die Bibliothek kennt zunaechst nur, was dieses Add-on selbst aufgenommen
hat. Dateien aus einer frueheren Fassung, aus einer anderen Installation
oder von Hand hineinkopierte Aufnahmen fehlen darin.

Der Suchlauf gleicht den Zielordner mit der Datenbank ab und traegt
Fehlendes nach. Vorhandene Eintraege bleiben unangetastet.
"""

import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import config, db, probe
from .recorder import safe_filename

# Was als Aufnahme gilt. Deckt sich mit dem, was das Add-on schreiben kann.
ENDUNGEN = {".mp3", ".aac", ".m4a", ".ogg", ".opus", ".flac"}

# Dateiname der eigenen Aufnahmen: <Sender>[_<Bezeichnung>]_<Zeitstempel>
STEMPEL = re.compile(
    r"^(?P<rest>.+?)_(?P<stempel>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})"
    r"(?:_(?P<nummer>\d+))?$")

# Dateien, die gerade erst geschrieben wurden, koennen noch unfertig sein -
# etwa waehrend eine Aufnahme zusammengefuegt wird.
MINDESTALTER_SEKUNDEN = 60


def scan(verzeichnis=None, mindestalter=MINDESTALTER_SEKUNDEN):
    """Traegt fehlende Aufnahmen nach. Liefert (gefunden, uebersprungen)."""
    wurzel = Path(verzeichnis or config.OUTPUT_DIR)
    if not wurzel.is_dir():
        print(f"[bibliothek] {wurzel} ist nicht erreichbar", flush=True)
        return 0, 0

    bekannt = {_vergleichbar(pfad) for pfad in db.known_output_files()}
    stationen = _stationsnamen()
    jung = datetime.now() - timedelta(seconds=mindestalter)

    gefunden, uebersprungen = 0, 0
    for pfad in sorted(wurzel.rglob("*")):
        if not pfad.is_file() or pfad.suffix.lower() not in ENDUNGEN:
            continue
        if _vergleichbar(pfad) in bekannt:
            continue

        try:
            zustand = pfad.stat()
        except OSError:
            continue
        if zustand.st_size == 0:
            uebersprungen += 1
            continue
        if datetime.fromtimestamp(zustand.st_mtime) > jung:
            # Wird vielleicht gerade noch geschrieben.
            uebersprungen += 1
            continue

        _eintragen(pfad, zustand, stationen)
        gefunden += 1

    if gefunden or uebersprungen:
        print(f"[bibliothek] Suchlauf in {wurzel}: {gefunden} neu erfasst, "
              f"{uebersprungen} uebersprungen", flush=True)
    return gefunden, uebersprungen


def _eintragen(pfad, zustand, stationen):
    beginn, sender, bezeichnung = _aus_dateiname(pfad, zustand, stationen)

    befund = probe.probe_file(pfad)
    dauer = befund.get("duration_seconds")
    ende = beginn + timedelta(seconds=dauer) if dauer else None

    kennung = "gef_" + uuid.uuid4().hex[:8]
    db.create_recording(
        recording_id=kennung,
        station_key="",
        station_name=sender,
        stream_url="",
        ext=pfad.suffix.lstrip(".").lower(),
        started_at=beginn.isoformat(timespec="seconds"),
        planned_end=(ende or beginn).isoformat(timespec="seconds"),
        work_dir="",
        label=bezeichnung,
        state="completed",
        discovered=True,
    )
    db.update_recording(
        kennung,
        ended_at=(ende or beginn).isoformat(timespec="seconds"),
        output_file=str(pfad),
        size_bytes=zustand.st_size,
        error=befund.get("fehler"),
    )


def _aus_dateiname(pfad, zustand, stationen):
    """Ermittelt Beginn, Sender und Bezeichnung so gut es der Name hergibt."""
    treffer = STEMPEL.match(pfad.stem)
    if not treffer:
        # Fremde Benennung: Zeitpunkt aus der Datei, Name als Bezeichnung.
        return (datetime.fromtimestamp(zustand.st_mtime),
                pfad.stem.replace("_", " "), "")

    try:
        beginn = datetime.strptime(treffer.group("stempel"), "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        beginn = datetime.fromtimestamp(zustand.st_mtime)

    rest = treffer.group("rest")
    for vorsilbe, name in stationen:
        if rest == vorsilbe:
            return beginn, name, ""
        if rest.startswith(vorsilbe + "_"):
            return beginn, name, rest[len(vorsilbe) + 1:].replace("_", " ")

    return beginn, rest.replace("_", " "), ""


def _stationsnamen():
    """Sendernamen in der Schreibweise, wie sie im Dateinamen landen.

    Die laengsten zuerst, damit 'SUNSHINE LIVE Classics' nicht faelschlich
    als 'SUNSHINE LIVE' mit der Bezeichnung 'Classics' gelesen wird.
    """
    paare = [(safe_filename(st["name"]), st["name"]) for st in db.list_stations()]
    paare = [(vorsilbe, name) for vorsilbe, name in paare if vorsilbe]
    return sorted(paare, key=lambda paar: len(paar[0]), reverse=True)


def _vergleichbar(pfad):
    """Pfad in einer Form, die sich zuverlaessig vergleichen laesst."""
    try:
        return str(Path(pfad).resolve()).lower()
    except OSError:
        return str(pfad).lower()
