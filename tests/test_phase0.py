"""Rauchtest: Datenbank, Aufnahme, Neustart, Fehlerfall, Scheduler, Web.

Braucht kein ffmpeg - der Aufruf wird durch tests/fake_ffmpeg.py ersetzt.
Aufruf:  python tests/test_phase0.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

WORK = Path(tempfile.mkdtemp(prefix="rr_test_"))
os.environ["DATA_DIR"] = str(WORK / "data")
os.environ["OUTPUT_DIR"] = str(WORK / "out")
os.environ["TZ"] = "Europe/Berlin"

# jobs.json der alten Fassung anlegen, damit die Uebernahme geprueft wird.
(WORK / "data").mkdir(parents=True, exist_ok=True)
(WORK / "data" / "jobs.json").write_text(json.dumps([{
    "id": "job_alt1", "name": "Alter Zeitplan", "station": "sunshine_live",
    "start_time": "22:00", "duration_minutes": 240,
    "weekdays": ["fri", "sat"], "enabled": True,
}]), encoding="utf-8")

sys.path.insert(0, str(PROJECT))

from radio_recorder import config, db, scheduler, web          # noqa: E402
from radio_recorder.recorder import Recorder                   # noqa: E402

# ffmpeg durch den Platzhalter ersetzen, Segmente auf 3 Sekunden verkuerzen.
config.FFMPEG = [sys.executable, str(HERE / "fake_ffmpeg.py")]
config.SEGMENT_MINUTES = 0.05

bestanden, fehlgeschlagen = [], []


def pruefe(bedingung, beschreibung, detail=""):
    if bedingung:
        bestanden.append(beschreibung)
        print(f"  OK   {beschreibung}")
    else:
        fehlgeschlagen.append(f"{beschreibung} {detail}".strip())
        print(f"  FEHL {beschreibung} {detail}")


def warte_auf_zustand(rid, nicht=("running",), timeout=30):
    grenze = time.monotonic() + timeout
    while time.monotonic() < grenze:
        rec = db.get_recording(rid)
        if rec and rec["state"] not in nicht:
            return rec
        time.sleep(0.3)
    return db.get_recording(rid)


print("\n=== 0. Dateien sind fuer Linux brauchbar ===")
# Windows-Zeilenenden in run.sh machen aus der Shebang "bashio\r". s6 meldet
# dann nur "exec: fatal: unable to exec bashio" und das Add-on startet nicht.
UEBERSPRINGEN = {".git", "legacy", "__pycache__", ".cursor"}
mit_crlf = [
    pfad.relative_to(PROJECT).as_posix()
    for pfad in PROJECT.rglob("*")
    if pfad.is_file()
    and not any(teil in UEBERSPRINGEN for teil in pfad.parts)
    and b"\r\n" in pfad.read_bytes()
]
pruefe(not mit_crlf, "Keine Datei hat Windows-Zeilenenden",
       f"-> {mit_crlf}")

shebang = (PROJECT / "run.sh").read_bytes().split(b"\n")[0]
pruefe(shebang == b"#!/usr/bin/with-contenv bashio",
       "Shebang von run.sh ist unversehrt", f"-> {shebang!r}")


print("\n=== 1. Datenbank und Uebernahme alter Zeitplaene ===")
db.init()
jobs = db.list_jobs()
pruefe(len(jobs) == 1, "jobs.json wurde uebernommen", f"-> {len(jobs)} Jobs")
pruefe(jobs and jobs[0]["weekdays"] == ["fri", "sat"],
       "Wochentage korrekt uebernommen", f"-> {jobs[0]['weekdays'] if jobs else None}")
pruefe(not (WORK / "data" / "jobs.json").exists(),
       "jobs.json wurde nach der Uebernahme umbenannt")
db.init()
pruefe(len(db.list_jobs()) == 1, "Zweiter init() verdoppelt nichts",
       f"-> {len(db.list_jobs())} Jobs")
pruefe(config.DB_FILE.exists(), "Datenbankdatei angelegt")


print("\n=== 2. Aufnahme mit Segmenten, danach Stopp ===")
rec1 = Recorder()
rid1 = rec1.start("sunshine_live", duration_minutes=1, label="Testlauf")
time.sleep(7)
laufend = rec1.active()
pruefe(len(laufend) == 1, "Aufnahme erscheint als laufend")
pruefe(laufend and laufend[0]["size_bytes"] > 0, "Es werden Daten geschrieben",
       f"-> {laufend[0]['size_bytes'] if laufend else 0} B")
segmente = sorted((config.WORK_DIR / rid1).glob("seg_*.mp3"))
pruefe(len(segmente) >= 2, "Mehrere Segmente angelegt", f"-> {len(segmente)}")

rec1.stop(rid1)
fertig = warte_auf_zustand(rid1)
pruefe(fertig["state"] == "cancelled", "Zustand nach Stopp = cancelled",
       f"-> {fertig['state']} / {fertig['error']}")
ziel = Path(fertig["output_file"] or "")
pruefe(ziel.exists(), "Zieldatei wurde erzeugt", f"-> {ziel}")
pruefe(fertig["size_bytes"] > 0, "Zieldatei ist nicht leer",
       f"-> {fertig['size_bytes']} B")
pruefe(not (config.WORK_DIR / rid1).exists(), "Arbeitsverzeichnis aufgeraeumt")
pruefe("Testlauf" in ziel.name and "SUNSHINE_LIVE" in ziel.name,
       "Dateiname enthaelt Sender und Bezeichnung", f"-> {ziel.name}")


print("\n=== 3. Absturz mitten in der Aufnahme, danach Fortsetzung ===")
rec2 = Recorder()
rid2 = rec2.start("sunshine_live", duration_minutes=1, label="Neustart")
time.sleep(5)
vorher = sorted((config.WORK_DIR / rid2).glob("seg_*.mp3"))
groesse_vorher = sum(s.stat().st_size for s in vorher)
rec2.shutdown(timeout=8)            # entspricht dem Stoppen des Add-ons

zwischenstand = db.get_recording(rid2)
pruefe(zwischenstand["state"] == "running",
       "Zustand bleibt nach dem Herunterfahren 'running'",
       f"-> {zwischenstand['state']}")
pruefe(len(vorher) >= 1, "Segmente aus dem ersten Lauf vorhanden",
       f"-> {len(vorher)}")

rec3 = Recorder()                   # entspricht dem Neustart des Add-ons
anzahl = rec3.resume_pending()
pruefe(anzahl == 1, "Aufnahme wurde fortgesetzt", f"-> {anzahl}")
time.sleep(6)
nachher = sorted((config.WORK_DIR / rid2).glob("seg_*.mp3"))
pruefe(len(nachher) > len(vorher), "Neue Segmente kamen hinzu",
       f"-> vorher {len(vorher)}, jetzt {len(nachher)}")
pruefe([s.name for s in nachher][:len(vorher)] == [s.name for s in vorher],
       "Alte Segmente blieben unveraendert erhalten")

rec3.stop(rid2)
fertig2 = warte_auf_zustand(rid2)
pruefe(fertig2["state"] == "cancelled", "Fortgesetzte Aufnahme abgeschlossen",
       f"-> {fertig2['state']} / {fertig2['error']}")
pruefe(fertig2["resume_count"] == 1, "Fortsetzung wurde vermerkt",
       f"-> {fertig2['resume_count']}")
ziel2 = Path(fertig2["output_file"] or "")
pruefe(ziel2.exists() and ziel2.stat().st_size > groesse_vorher,
       "Ergebnis enthaelt beide Abschnitte",
       f"-> {ziel2.stat().st_size if ziel2.exists() else 0} B "
       f"(vor dem Neustart: {groesse_vorher} B)")


print("\n=== 4. Endzeit lag im Ausfallzeitraum ===")
rid3 = "abgelaufen"
wd = config.WORK_DIR / rid3
wd.mkdir(parents=True, exist_ok=True)
(wd / "seg_00000.mp3").write_bytes(b"\x01" * 4096)
db.create_recording(
    recording_id=rid3, station_key="sunshine_live", station_name="SUNSHINE LIVE",
    stream_url="http://example.invalid/stream", ext="mp3",
    started_at=(datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds"),
    planned_end=(datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds"),
    work_dir=str(wd), label="Abgelaufen")
rec4 = Recorder()
rec4.resume_pending()
abgelaufen = db.get_recording(rid3)
pruefe(abgelaufen["state"] == "completed",
       "Abgelaufene Aufnahme wird abgeschlossen statt neu gestartet",
       f"-> {abgelaufen['state']}")
pruefe(Path(abgelaufen["output_file"] or "").exists(),
       "Gerettete Datei liegt im Zielordner")


print("\n=== 5a. Nicht erreichbarer Stream wird sichtbar ===")
config.MAX_STREAM_RETRIES = 2
config.RETRY_BACKOFF_SECONDS = 1
os.environ["RR_FAKE_FAIL"] = "1"
rec5 = Recorder()
rid4 = rec5.start("sunshine_live", duration_minutes=1, label="Kaputt")
kaputt = warte_auf_zustand(rid4, timeout=30)
del os.environ["RR_FAKE_FAIL"]
pruefe(kaputt["state"] == "failed", "Zustand = failed", f"-> {kaputt['state']}")
pruefe(kaputt["retry_count"] == config.MAX_STREAM_RETRIES + 1,
       "Es wurde mehrfach neu verbunden", f"-> {kaputt['retry_count']}")
pruefe("404" in (kaputt["error"] or ""),
       "Fehlertext nennt die Ursache aus ffmpeg", f"-> {kaputt['error']!r}")


print("\n=== 5b. Fehlendes ffmpeg bricht sofort ab ===")
merker = config.FFMPEG
config.FFMPEG = ["gibtesnicht_ffmpeg"]
rec6 = Recorder()
begonnen = time.monotonic()
rid5 = rec6.start("sunshine_live", duration_minutes=1, label="Ohne ffmpeg")
# Windows braucht rund 17 s, um einen fehlenden Befehl abzulehnen; unter
# Linux passiert das sofort. Der Test prueft nur, dass nicht wiederholt wird.
fehlt = warte_auf_zustand(rid5, timeout=60)
dauer = time.monotonic() - begonnen
config.FFMPEG = merker
pruefe(fehlt["state"] == "failed", "Zustand = failed", f"-> {fehlt['state']}")
pruefe(fehlt["retry_count"] == 0, "Kein zweiter Versuch",
       f"-> {fehlt['retry_count']} Versuche nach {dauer:.1f}s")
pruefe("ffmpeg" in (fehlt["error"] or "").lower(),
       "Fehlertext nennt ffmpeg", f"-> {fehlt['error']!r}")


print("\n=== 6. Scheduler und Zeitzone ===")
tz = scheduler.resolve_timezone()
pruefe(tz is not None and "Berlin" in str(tz), "Zeitzone wird aufgeloest",
       f"-> {tz}")
pruefe(scheduler.parse_start_time("22:05") == (22, 5), "Startzeit wird geparst")
try:
    scheduler.parse_start_time("25:99")
    pruefe(False, "Unsinnige Startzeit wird abgelehnt")
except ValueError:
    pruefe(True, "Unsinnige Startzeit wird abgelehnt")
try:
    scheduler.validate_weekdays([])
    pruefe(False, "Leere Wochentagsauswahl wird abgelehnt")
except ValueError:
    pruefe(True, "Leere Wochentagsauswahl wird abgelehnt")
pruefe(scheduler.validate_weekdays(["sat", "mon", "quatsch"]) == ["mon", "sat"],
       "Wochentage werden gefiltert und sortiert")

scheduler.start()
naechste = scheduler.next_runs()
pruefe("job_alt1" in naechste and naechste["job_alt1"] is not None,
       "Uebernommener Zeitplan ist eingetragen", f"-> {naechste}")
lauf = naechste.get("job_alt1")
pruefe(lauf is not None and lauf.hour == 22 and lauf.minute == 0,
       "Naechster Lauf um 22:00 Ortszeit", f"-> {lauf}")
pruefe(lauf is not None and lauf.weekday() in (4, 5),
       "Naechster Lauf faellt auf Fr oder Sa", f"-> {lauf}")


print("\n=== 7. Weboberflaeche ===")
app = web.create_app()
app.config["TESTING"] = True
client = app.test_client()

antwort = client.get("/")
pruefe(antwort.status_code == 200, "Startseite laedt", f"-> {antwort.status_code}")
seite = antwort.get_data(as_text=True)
pruefe("Radio Recorder" in seite, "Ueberschrift vorhanden")
pruefe("Alter Zeitplan" in seite, "Uebernommener Zeitplan wird angezeigt")
pruefe("Europe/Berlin" in seite, "Zeitzone wird angezeigt")

bibliothek = client.get("/recordings").get_data(as_text=True)
pruefe("fehlgeschlagen" in bibliothek,
       "Fehlgeschlagene Aufnahme wird in der Bibliothek angezeigt")

gesundheit = client.get("/health").get_json()
pruefe(gesundheit["ok"] is True and gesundheit["timezone"] == "Europe/Berlin",
       "health liefert Zeitzone", f"-> {gesundheit}")
status = client.get("/api/status").get_json()
pruefe("active" in status, "Statusabfrage antwortet", f"-> {status}")

vorher_jobs = len(db.list_jobs())
client.post("/schedule/add", data={
    "name": "Neuer Plan", "station": "sunshine_live", "start_time": "06:30",
    "hours": "1", "minutes": "30", "weekday": ["mon", "tue"]})
pruefe(len(db.list_jobs()) == vorher_jobs + 1, "Zeitplan ueber Web angelegt")

client.post("/schedule/add", data={
    "name": "Ohne Tage", "station": "sunshine_live", "start_time": "06:30",
    "hours": "1", "minutes": "0"})
pruefe(len(db.list_jobs()) == vorher_jobs + 1,
       "Zeitplan ohne Wochentag wird abgelehnt")

client.post("/schedule/add", data={
    "name": "Zu lang", "station": "sunshine_live", "start_time": "06:30",
    "hours": "25", "minutes": "0", "weekday": ["mon"]})
pruefe(len(db.list_jobs()) == vorher_jobs + 1,
       "Dauer ueber 24 Stunden wird abgelehnt")

neuer = [j for j in db.list_jobs() if j["name"] == "Neuer Plan"][0]
client.post(f"/schedule/toggle/{neuer['id']}")
pruefe(db.get_job(neuer["id"])["enabled"] is False, "Zeitplan pausierbar")
client.post(f"/schedule/delete/{neuer['id']}")
pruefe(db.get_job(neuer["id"]) is None, "Zeitplan loeschbar")

antwort = client.post("/start", data={"station": "nichtvorhanden",
                                      "hours": "1", "minutes": "0"})
pruefe(antwort.status_code in (302, 303), "Unbekannter Sender fuehrt nicht zum Absturz",
       f"-> {antwort.status_code}")


print("\n=== 8. Lange Aufnahmen und Speicherplatz ===")
from radio_recorder import recorder as recorder_mod            # noqa: E402

station = db.get_station("sunshine_live")
pruefe(recorder_mod.estimate_bytes(station, 60) == 86_400_000,
       "Platzbedarf fuer eine Stunde bei 192 kbit/s",
       f"-> {recorder_mod.estimate_bytes(station, 60)}")
pruefe(recorder_mod.estimate_bytes(station, 12 * 60) == 1_036_800_000,
       "Platzbedarf fuer zwoelf Stunden",
       f"-> {recorder_mod.estimate_bytes(station, 12*60)}")
pruefe(recorder_mod.free_bytes(config.WORK_DIR) is not None,
       "Freier Platz ist ermittelbar")

rec7 = Recorder()
rid6 = rec7.start("sunshine_live", duration_minutes=10 * 60, label="Zehn Stunden")
lang = db.get_recording(rid6)
spanne = (datetime.fromisoformat(lang["planned_end"])
          - datetime.fromisoformat(lang["started_at"]))
pruefe(spanne == timedelta(hours=10), "Zehn-Stunden-Aufnahme wird angenommen",
       f"-> {spanne}")
rec7.stop(rid6)
warte_auf_zustand(rid6)

merk_frei = config.MIN_FREE_MB
config.MIN_FREE_MB = 10 ** 9          # unerfuellbar viel verlangen
try:
    Recorder().start("sunshine_live", duration_minutes=60, label="Kein Platz")
    pruefe(False, "Start bei zu wenig Platz wird abgelehnt")
except ValueError as err:
    pruefe("Speicherplatz" in str(err), "Start bei zu wenig Platz wird abgelehnt",
           f"-> {err}")
config.MIN_FREE_MB = merk_frei

config.SPACE_CHECK_SECONDS = 2
rec8 = Recorder()
rid7 = rec8.start("sunshine_live", duration_minutes=60, label="Platz geht aus")
time.sleep(1)
config.MIN_FREE_MB = 10 ** 9          # Platz geht mitten in der Aufnahme aus
knapp = warte_auf_zustand(rid7, timeout=30)
config.MIN_FREE_MB = merk_frei
pruefe(knapp["state"] == "cancelled",
       "Aufnahme stoppt von selbst statt zu scheitern", f"-> {knapp['state']}")
pruefe("frei" in (knapp["error"] or ""), "Grund wird vermerkt",
       f"-> {knapp['error']!r}")
pruefe(Path(knapp["output_file"] or "").exists() and knapp["size_bytes"] > 0,
       "Das bis dahin Aufgenommene bleibt erhalten",
       f"-> {knapp['size_bytes']} B")


scheduler.shutdown()
print("\n" + "=" * 62)
print(f"Bestanden: {len(bestanden)}   Fehlgeschlagen: {len(fehlgeschlagen)}")
for eintrag in fehlgeschlagen:
    print(f"  - {eintrag}")
print("=" * 62)
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if fehlgeschlagen else 0)
