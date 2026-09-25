"""Rauchtest Phase 1: Sender, Codec-Erkennung, Endzeit, Bibliothek.

Braucht weder ffmpeg noch Internet - beides wird ersetzt.
Aufruf aus dem Projektordner:  python tests/test_phase1.py
"""

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent / "radio_recorder"      # der Add-on-Ordner

WORK = Path(tempfile.mkdtemp(prefix="rr_p1_"))
os.environ["DATA_DIR"] = str(WORK / "data")
os.environ["OUTPUT_DIR"] = str(WORK / "out")
os.environ["TZ"] = "Europe/Berlin"
(WORK / "data").mkdir(parents=True, exist_ok=True)
(WORK / "out").mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT))

from radio_recorder import config, db, directory, probe, scheduler, web  # noqa: E402

config.FFMPEG = [sys.executable, str(HERE / "fake_ffmpeg.py")]

bestanden, fehlgeschlagen = [], []


def pruefe(bedingung, beschreibung, detail=""):
    if bedingung:
        bestanden.append(beschreibung)
        print(f"  OK   {beschreibung}")
    else:
        fehlgeschlagen.append(f"{beschreibung} {detail}".strip())
        print(f"  FEHL {beschreibung} {detail}")


# --------------------------------------------------------------------------
print("\n=== 1. Datenbank von Stand 1 auf Stand 2 heben ===")

# Eine Datenbank im alten Zustand nachbauen, so wie sie beim Anwender liegt.
alt = WORK / "data" / "alt.db"
verbindung = sqlite3.connect(str(alt))
verbindung.executescript("""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, station TEXT NOT NULL,
    start_time TEXT NOT NULL, duration_minutes INTEGER NOT NULL,
    weekdays TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL);
CREATE TABLE recordings (
    id TEXT PRIMARY KEY, job_id TEXT, label TEXT NOT NULL DEFAULT '',
    station_key TEXT NOT NULL, station_name TEXT NOT NULL,
    stream_url TEXT NOT NULL, ext TEXT NOT NULL DEFAULT 'mp3',
    state TEXT NOT NULL, started_at TEXT NOT NULL, planned_end TEXT NOT NULL,
    ended_at TEXT, work_dir TEXT, output_file TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    resume_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0, error TEXT);
INSERT INTO meta VALUES ('schema_version', '1');
INSERT INTO jobs VALUES
  ('job_alt', 'Freitag Nacht', 'sunshine_live', '22:00', 300,
   'fri,sat', 1, '2026-09-01T10:00:00');
""")
verbindung.commit()
verbindung.close()

config.DB_FILE = alt
db._initialised = False
db.init()

jobs = db.list_jobs()
pruefe(len(jobs) == 1 and jobs[0]["name"] == "Freitag Nacht",
       "Vorhandener Zeitplan bleibt erhalten", f"-> {jobs}")
pruefe(jobs[0]["lead_in_minutes"] == 0 and jobs[0]["lead_out_minutes"] == 0,
       "Neue Spalten sind vorbelegt")
pruefe(jobs[0]["end_time"] is None, "Endzeit ist zunaechst leer")
pruefe(len(db.list_stations()) == 1,
       "Fest eingebauter Sender wurde angelegt", f"-> {db.list_stations()}")
with db.connect() as conn:
    stand = conn.execute(
        "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
pruefe(stand == "2", "Schema-Stand ist jetzt 2", f"-> {stand}")

db._initialised = False
db.init()
pruefe(len(db.list_jobs()) == 1 and len(db.list_stations()) == 1,
       "Zweiter Durchlauf verdoppelt nichts")

# Ab hier mit einer frischen Datenbank weiterarbeiten.
config.DB_FILE = WORK / "data" / "test.db"
db._initialised = False
db.init()


# --------------------------------------------------------------------------
print("\n=== 2. Sender verwalten ===")

key = db.add_station(name="Deutschlandfunk", url="https://example.invalid/dlf")
pruefe(key == "deutschlandfunk", "Kurzname wird aus dem Namen gebildet",
       f"-> {key}")

zweiter = db.add_station(name="Deutschlandfunk", url="https://example.invalid/dlf2")
pruefe(zweiter == "deutschlandfunk_2", "Gleicher Name bekommt eigenen Kurznamen",
       f"-> {zweiter}")

try:
    db.add_station(name="Noch mal", url="https://example.invalid/dlf")
    pruefe(False, "Gleiche Adresse wird abgelehnt")
except ValueError as err:
    pruefe("bereits" in str(err), "Gleiche Adresse wird abgelehnt", f"-> {err}")

for falsch in ("", "  ", "ftp://example.invalid/x", "example.invalid/x"):
    try:
        db.add_station(name="Falsch", url=falsch)
        pruefe(False, f"Adresse {falsch!r} wird abgelehnt")
    except ValueError:
        pruefe(True, f"Adresse {falsch!r} wird abgelehnt")

try:
    db.add_station(name="", url="https://example.invalid/ohne-namen")
    pruefe(False, "Sender ohne Namen wird abgelehnt")
except ValueError:
    pruefe(True, "Sender ohne Namen wird abgelehnt")

db.add_job(name="Nutzt DLF", station=key, start_time="06:00",
           duration_minutes=60, weekdays=["mon"])
try:
    db.delete_station(key)
    pruefe(False, "Benutzter Sender wird nicht geloescht")
except ValueError as err:
    pruefe("Nutzt DLF" in str(err), "Benutzter Sender wird nicht geloescht",
           f"-> {err}")

pruefe(db.delete_station(zweiter), "Unbenutzter Sender laesst sich loeschen")
pruefe(db.get_station(zweiter) is None, "Sender ist danach weg")


# --------------------------------------------------------------------------
print("\n=== 3. Codec und Dateiendung erkennen ===")

pruefe(probe.extension_for("mp3") == "mp3", "mp3 -> .mp3")
pruefe(probe.extension_for("aac") == "aac", "aac -> .aac")
pruefe(probe.extension_for("aac_latm") == "aac", "aac_latm -> .aac")
pruefe(probe.extension_for("opus") == "opus", "opus -> .opus")
pruefe(probe.extension_for("unbekannt") == "mp3", "Unbekanntes faellt auf mp3 zurueck")
pruefe(probe.segment_format_for("aac") == "adts",
       "Segmentformat fuer aac ist adts", f"-> {probe.segment_format_for('aac')}")

for modus, erwartet_ext, erwartet_rate in (("mp3", "mp3", 128),
                                           ("aac", "aac", 96),
                                           ("opus", "opus", 64)):
    os.environ["RR_FAKE_PROBE"] = modus
    befund = probe.probe_stream("https://example.invalid/stream")
    pruefe(befund["ext"] == erwartet_ext and befund["bitrate_kbps"] == erwartet_rate
           and befund["fehler"] is None,
           f"Stream mit {modus} wird richtig erkannt", f"-> {befund}")

os.environ["RR_FAKE_PROBE"] = "mp3"
befund = probe.probe_stream("https://example.invalid/stream")
pruefe(befund["name"] == "Test-Sender FM", "Sendername wird aus dem Stream gelesen",
       f"-> {befund['name']}")

os.environ["RR_FAKE_PROBE"] = "fehler"
befund = probe.probe_stream("https://example.invalid/kaputt")
pruefe(befund["fehler"] and "404" in befund["fehler"],
       "Nicht erreichbarer Stream meldet den Grund", f"-> {befund['fehler']}")
pruefe(befund["ext"] == "mp3" and befund["bitrate_kbps"] == 192,
       "Trotz Fehler gibt es brauchbare Vorgaben")

os.environ["RR_FAKE_PROBE"] = "leer"
befund = probe.probe_stream("https://example.invalid/stumm")
pruefe("keine Tonspur" in (befund["fehler"] or ""),
       "Stream ohne Tonspur wird gemeldet", f"-> {befund['fehler']}")
os.environ["RR_FAKE_PROBE"] = "mp3"


# --------------------------------------------------------------------------
print("\n=== 4. Endzeit, Vorlauf und Nachlauf ===")

pruefe(scheduler.duration_from_end("22:00", "23:30") == 90,
       "Endzeit am selben Tag")
pruefe(scheduler.duration_from_end("22:00", "02:00") == 240,
       "Endzeit nach Mitternacht",
       f"-> {scheduler.duration_from_end('22:00', '02:00')}")
pruefe(scheduler.duration_from_end("06:00", "06:00") == 1440,
       "Gleiche Zeit bedeutet volle 24 Stunden")
pruefe(scheduler.end_time_from_duration("22:00", 300) == "03:00",
       "Endzeit aus Dauer, ueber Mitternacht",
       f"-> {scheduler.end_time_from_duration('22:00', 300)}")

# Das Ergebnis steht in Wochenreihenfolge, beginnend mit Montag.
pruefe(scheduler.shift_weekdays(["mon", "tue"], -1) == ["mon", "sun"],
       "Wochentage lassen sich zurueckschieben",
       f"-> {scheduler.shift_weekdays(['mon','tue'], -1)}")
pruefe(scheduler.shift_weekdays(["fri"], -1) == ["thu"],
       "Freitag minus ein Tag ist Donnerstag")

einfach = {"start_time": "22:00", "duration_minutes": 300,
           "weekdays": ["fri"], "lead_in_minutes": 0, "lead_out_minutes": 0}
pruefe(scheduler.effective_schedule(einfach) == (22, 0, ["fri"], 300),
       "Ohne Vor-/Nachlauf bleibt alles unveraendert",
       f"-> {scheduler.effective_schedule(einfach)}")

mit_lauf = dict(einfach, lead_in_minutes=2, lead_out_minutes=3)
pruefe(scheduler.effective_schedule(mit_lauf) == (21, 58, ["fri"], 305),
       "Vorlauf zieht den Start vor, Nachlauf verlaengert",
       f"-> {scheduler.effective_schedule(mit_lauf)}")

ueber_mitternacht = {"start_time": "00:01", "duration_minutes": 60,
                     "weekdays": ["mon"], "lead_in_minutes": 5,
                     "lead_out_minutes": 0}
ergebnis = scheduler.effective_schedule(ueber_mitternacht)
pruefe(ergebnis == (23, 56, ["sun"], 65),
       "Vorlauf ueber Mitternacht verschiebt auch den Wochentag",
       f"-> {ergebnis}")


# --------------------------------------------------------------------------
print("\n=== 5. Sendersuche im Verzeichnis ===")

ANTWORT = [
    {"name": "Sunshine Live", "url": "http://alt.example/x",
     "url_resolved": "https://example.invalid/sunshine", "codec": "MP3",
     "bitrate": 192, "country": "Germany", "homepage": "https://example.invalid"},
    {"name": "Ohne Adresse", "url": "", "url_resolved": ""},
    {"name": "", "url_resolved": "https://example.invalid/namenlos"},
    {"name": "Falsches Schema", "url_resolved": "ftp://example.invalid/x"},
    "kein Woerterbuch",
]

original = directory._hole
directory._hole = lambda adresse: ANTWORT
try:
    treffer = directory.search("sunshine")
    pruefe(len(treffer) == 1, "Unbrauchbare Eintraege werden aussortiert",
           f"-> {len(treffer)}")
    pruefe(treffer[0]["url"] == "https://example.invalid/sunshine",
           "Die aufgeloeste Adresse wird bevorzugt", f"-> {treffer[0]['url']}")
    pruefe(treffer[0]["codec"] == "mp3", "Codec wird kleingeschrieben")
    pruefe(treffer[0]["bitrate_kbps"] == 192, "Bitrate wird uebernommen")

    for zu_kurz in ("", "a", "  "):
        try:
            directory.search(zu_kurz)
            pruefe(False, f"Suche nach {zu_kurz!r} wird abgelehnt")
        except directory.DirectoryError:
            pruefe(True, f"Suche nach {zu_kurz!r} wird abgelehnt")

    def platzt(adresse):
        raise TimeoutError("Zeitueberschreitung")

    directory._hole = platzt
    try:
        directory.search("sunshine")
        pruefe(False, "Netzfehler wird als DirectoryError gemeldet")
    except directory.DirectoryError as err:
        pruefe("erreichbar" in str(err),
               "Netzfehler wird als DirectoryError gemeldet", f"-> {err}")
finally:
    directory._hole = original


# --------------------------------------------------------------------------
print("\n=== 6. Weboberflaeche: Sender, Zeitplan, Bibliothek ===")

app = web.create_app()
app.config["TESTING"] = True
client = app.test_client()

for pfad, kennzeichen in (("/", "Manuelle Aufnahme"),
                          ("/stations", "Sender suchen"),
                          ("/recordings", "Aufnahmen")):
    antwort = client.get(pfad)
    inhalt = antwort.get_data(as_text=True)
    pruefe(antwort.status_code == 200 and kennzeichen in inhalt,
           f"Seite {pfad} laedt", f"-> {antwort.status_code}")

vorher = len(db.list_stations())
client.post("/stations/add", data={"url": "https://example.invalid/neu"})
stations = db.list_stations()
pruefe(len(stations) == vorher + 1, "Sender ueber das Web angelegt")
neuer = [s for s in stations if s["url"] == "https://example.invalid/neu"][0]
pruefe(neuer["name"] == "Test-Sender FM",
       "Fehlender Name wird aus dem Stream ergaenzt", f"-> {neuer['name']}")
pruefe(neuer["codec"] == "mp3" and neuer["bitrate_kbps"] == 128,
       "Codec und Bitrate wurden ermittelt", f"-> {neuer}")

client.post("/stations/add", data={"name": "Krumm", "url": "nicht-mal-eine-url"})
pruefe(len(db.list_stations()) == vorher + 1, "Unsinnige Adresse wird abgelehnt")

os.environ["RR_FAKE_PROBE"] = "aac"
client.post(f"/stations/recheck/{neuer['key']}")
geprueft = db.get_station(neuer["key"])
pruefe(geprueft["ext"] == "aac" and geprueft["codec"] == "aac",
       "Erneute Pruefung aktualisiert das Format", f"-> {geprueft['ext']}")
pruefe(geprueft["checked_at"], "Zeitpunkt der Pruefung wird vermerkt")
os.environ["RR_FAKE_PROBE"] = "mp3"

zeitplaene_vorher = len(db.list_jobs())
client.post("/schedule/add", data={
    "name": "Per Endzeit", "station": neuer["key"], "start_time": "22:00",
    "modus": "endzeit", "end_time": "02:00", "weekday": ["fri"],
    "lead_in": "2", "lead_out": "3"})
plan = [j for j in db.list_jobs() if j["name"] == "Per Endzeit"]
pruefe(len(plan) == 1, "Zeitplan mit Endzeit angelegt")
pruefe(plan and plan[0]["duration_minutes"] == 240,
       "Dauer wurde aus der Endzeit errechnet",
       f"-> {plan[0]['duration_minutes'] if plan else None}")
pruefe(plan and plan[0]["lead_in_minutes"] == 2 and plan[0]["lead_out_minutes"] == 3,
       "Vor- und Nachlauf wurden gespeichert")

client.post("/schedule/add", data={
    "name": "Ohne Endzeit", "station": neuer["key"], "start_time": "22:00",
    "modus": "endzeit", "weekday": ["fri"]})
pruefe(len(db.list_jobs()) == zeitplaene_vorher + 1,
       "Endzeit-Modus ohne Endzeit wird abgelehnt")

client.post("/schedule/add", data={
    "name": "Zu viel", "station": neuer["key"], "start_time": "22:00",
    "hours": "25", "minutes": "0", "weekday": ["fri"]})
pruefe(len(db.list_jobs()) == zeitplaene_vorher + 1,
       "25 Stunden werden abgelehnt statt gekuerzt")

client.post("/schedule/add", data={
    "name": "Unsinniger Vorlauf", "station": neuer["key"], "start_time": "22:00",
    "hours": "1", "minutes": "0", "weekday": ["fri"], "lead_in": "999"})
pruefe(len(db.list_jobs()) == zeitplaene_vorher + 1,
       "Unsinniger Vorlauf wird abgelehnt")


print("\n--- Bibliothek: Dateien ausliefern und loeschen ---")
datei = config.OUTPUT_DIR / "Testaufnahme.mp3"
datei.write_bytes(b"\xff\xfb" + b"\x00" * 5000)
jetzt = datetime.now()
db.create_recording(
    recording_id="bib1", station_key=neuer["key"], station_name="Test-Sender FM",
    stream_url="https://example.invalid/neu", ext="mp3", label="Bibliothek",
    started_at=(jetzt - timedelta(hours=1)).isoformat(timespec="seconds"),
    planned_end=jetzt.isoformat(timespec="seconds"), work_dir="")
db.update_recording("bib1", state="completed",
                    ended_at=jetzt.isoformat(timespec="seconds"),
                    output_file=str(datei), size_bytes=datei.stat().st_size)

seite = client.get("/recordings").get_data(as_text=True)
pruefe("Testaufnahme.mp3" in seite, "Aufnahme erscheint in der Bibliothek")

antwort = client.get("/recordings/download/bib1")
pruefe(antwort.status_code == 200 and len(antwort.data) == 5002,
       "Herunterladen liefert die Datei", f"-> {antwort.status_code}")
pruefe("attachment" in antwort.headers.get("Content-Disposition", ""),
       "Herunterladen wird als Anhang ausgeliefert")

antwort = client.get("/recordings/play/bib1")
pruefe(antwort.status_code == 200
       and antwort.headers.get("Content-Type", "").startswith("audio/mpeg"),
       "Abspielen liefert Ton", f"-> {antwort.headers.get('Content-Type')}")

antwort = client.get("/recordings/play/bib1", headers={"Range": "bytes=0-99"})
pruefe(antwort.status_code == 206, "Springen im Stueck wird unterstuetzt",
       f"-> {antwort.status_code}")

# Eine Aufnahme, deren Datei ausserhalb des Zielordners liegt, darf nicht
# ausgeliefert werden - egal was in der Datenbank steht.
fremd = WORK / "geheim.mp3"
fremd.write_bytes(b"geheim")
db.create_recording(
    recording_id="fremd", station_key=neuer["key"], station_name="X",
    stream_url="https://example.invalid/x", ext="mp3",
    started_at=jetzt.isoformat(timespec="seconds"),
    planned_end=jetzt.isoformat(timespec="seconds"), work_dir="")
db.update_recording("fremd", state="completed", output_file=str(fremd))
antwort = client.get("/recordings/download/fremd")
pruefe(antwort.status_code == 404,
       "Datei ausserhalb des Zielordners wird nicht ausgeliefert",
       f"-> {antwort.status_code}")
pruefe(fremd.exists(), "Fremde Datei bleibt unangetastet")

db.create_recording(
    recording_id="laeuft", station_key=neuer["key"], station_name="X",
    stream_url="https://example.invalid/x", ext="mp3",
    started_at=jetzt.isoformat(timespec="seconds"),
    planned_end=(jetzt + timedelta(hours=1)).isoformat(timespec="seconds"),
    work_dir="")
client.post("/recordings/delete/laeuft")
pruefe(db.get_recording("laeuft") is not None,
       "Laufende Aufnahme wird nicht geloescht")

client.post("/recordings/delete/bib1")
pruefe(db.get_recording("bib1") is None and not datei.exists(),
       "Loeschen entfernt Eintrag und Datei")

antwort = client.get("/recordings/download/gibtesnicht")
pruefe(antwort.status_code == 404, "Unbekannte Aufnahme liefert 404",
       f"-> {antwort.status_code}")

gesundheit = client.get("/health").get_json()
pruefe(gesundheit["stations"] == len(db.list_stations()),
       "health meldet die Zahl der Sender", f"-> {gesundheit}")


print("\n" + "=" * 62)
print(f"Bestanden: {len(bestanden)}   Fehlgeschlagen: {len(fehlgeschlagen)}")
for eintrag in fehlgeschlagen:
    print(f"  - {eintrag}")
print("=" * 62)
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if fehlgeschlagen else 0)
