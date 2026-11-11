"""Rauchtest Phase 2: Speicherziele - Kopie fertiger Aufnahmen in die Cloud.

Braucht weder rclone noch Internet: rclone wird durch tests/fake_rclone.py
ersetzt, die "Cloud" ist ein Ordner. ffmpeg ersetzt wie ueberall
tests/fake_ffmpeg.py.
Aufruf aus dem Projektordner:  python tests/test_phase2.py
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PROJECT = REPO / "radio_recorder"

WORK = Path(tempfile.mkdtemp(prefix="rr_p2_"))
CLOUD_ORDNER = WORK / "cloud"
RCLONE_LOG = WORK / "rclone.log"
os.environ["DATA_DIR"] = str(WORK / "data")
os.environ["OUTPUT_DIR"] = str(WORK / "out")
os.environ["TZ"] = "Europe/Berlin"
os.environ["RR_FAKE_RCLONE_CLOUD"] = str(CLOUD_ORDNER)
os.environ["RR_FAKE_RCLONE_LOG"] = str(RCLONE_LOG)
os.environ["RR_FAKE_RCLONE_ZAEHLER"] = str(WORK / "rclone.zaehler")
sys.path.insert(0, str(PROJECT))

from radio_recorder import __version__, cloud, config, db, web, zeit  # noqa: E402
from radio_recorder.recorder import Recorder                          # noqa: E402

config.FFMPEG = [sys.executable, str(HERE / "fake_ffmpeg.py")]
config.SEGMENT_MINUTES = 0.05
config.RCLONE = [sys.executable, str(HERE / "fake_rclone.py")]
cloud.PAUSE_SEKUNDEN = 0

PASSWORT = "g3h3im,mit:Sonderzeichen"

bestanden, fehlgeschlagen = [], []


def pruefe(bedingung, beschreibung, detail=""):
    if bedingung:
        bestanden.append(beschreibung)
        print(f"  OK   {beschreibung}")
    else:
        fehlgeschlagen.append(f"{beschreibung} {detail}".strip())
        print(f"  FEHL {beschreibung} {detail}")


def aufrufe():
    if not RCLONE_LOG.exists():
        return []
    return [json.loads(z) for z in RCLONE_LOG.read_text(encoding="utf-8").splitlines()
            if z.strip()]


def kopieraufrufe():
    return [a for a in aufrufe() if a and a[0] == "copy"]


def log_leeren():
    if RCLONE_LOG.exists():
        RCLONE_LOG.unlink()


def cloud_aus():
    config.CLOUD_TYPE = "aus"
    config.CLOUD_URL = config.CLOUD_USER = config.CLOUD_PASSWORD = ""
    config.CLOUD_PATH = config.CLOUD_REMOTE = ""
    config.CLOUD_BWLIMIT_KBYTE = 0
    config.CLOUD_AUTO = False


def webdav_einrichten():
    cloud_aus()
    config.CLOUD_TYPE = "webdav"
    config.CLOUD_URL = "https://cloud.example/remote.php/dav/files/jens"
    config.CLOUD_USER = "jens"
    config.CLOUD_PASSWORD = PASSWORT
    config.CLOUD_PATH = "Radio"


def lege_aufnahme_an(rid, job_id=None, inhalt=None):
    """Eine fertige Aufnahme samt Datei im Zielordner."""
    inhalt = inhalt or (b"ID3" + rid.encode() + b"\x00" * 2048)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    datei = config.OUTPUT_DIR / f"SUNSHINE_LIVE_{rid}.mp3"
    datei.write_bytes(inhalt)
    jetzt = zeit.text(zeit.jetzt())
    db.create_recording(
        recording_id=rid, station_key="sunshine_live",
        station_name="SUNSHINE LIVE", stream_url="https://example.invalid/s",
        ext="mp3", started_at=jetzt, planned_end=jetzt, work_dir="",
        job_id=job_id, state="completed")
    db.update_recording(rid, ended_at=jetzt, output_file=str(datei),
                        size_bytes=len(inhalt))
    return datei


def in_der_cloud(datei, remote="radio_recorder_cloud", pfad="Radio"):
    return CLOUD_ORDNER / remote / pfad / datei.name


def warte_auf_zustand(rid, nicht=("running",), timeout=40):
    grenze = time.monotonic() + timeout
    while time.monotonic() < grenze:
        rec = db.get_recording(rid)
        if rec and rec["state"] not in nicht:
            return rec
        time.sleep(0.3)
    return db.get_recording(rid)


def gespielte_aufnahme(rid, job_id=None):
    """Legt eine laufende Aufnahme von drei Sekunden an, wie nach einem Neustart."""
    arbeit = config.WORK_DIR / rid
    arbeit.mkdir(parents=True, exist_ok=True)
    db.create_recording(
        recording_id=rid, station_key="sunshine_live",
        station_name="SUNSHINE LIVE", stream_url="https://example.invalid/s",
        ext="mp3", started_at=zeit.text(zeit.jetzt()),
        planned_end=zeit.text(zeit.plus_sekunden(zeit.jetzt(), 3)),
        work_dir=str(arbeit), label=rid, job_id=job_id)


print("\n=== 1. Datenbank von Stand 6 auf Stand 7 heben ===")

# Stand 6, so wie er bei Anwendern mit echten Zeitplaenen und Aufnahmen liegt.
neu_db = config.DB_FILE
alt = WORK / "data" / "stand6.db"
alt.parent.mkdir(parents=True, exist_ok=True)
verbindung = sqlite3.connect(str(alt))
verbindung.executescript("""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE stations (
    key TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
    ext TEXT NOT NULL DEFAULT 'mp3', codec TEXT,
    bitrate_kbps INTEGER NOT NULL DEFAULT 192, country TEXT, homepage TEXT,
    source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL,
    checked_at TEXT, metadata_state TEXT, metadata_checked_at TEXT,
    metadata_sample TEXT, title_filters TEXT);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, station TEXT NOT NULL,
    start_time TEXT NOT NULL, duration_minutes INTEGER NOT NULL,
    end_time TEXT, lead_in_minutes INTEGER NOT NULL DEFAULT 0,
    lead_out_minutes INTEGER NOT NULL DEFAULT 0, weekdays TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE recordings (
    id TEXT PRIMARY KEY, job_id TEXT, label TEXT NOT NULL DEFAULT '',
    station_key TEXT NOT NULL, station_name TEXT NOT NULL,
    stream_url TEXT NOT NULL, ext TEXT NOT NULL DEFAULT 'mp3',
    state TEXT NOT NULL, started_at TEXT NOT NULL, planned_end TEXT NOT NULL,
    ended_at TEXT, work_dir TEXT, output_file TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    resume_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0, error TEXT,
    discovered INTEGER NOT NULL DEFAULT 0);
CREATE TABLE track_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, recording_id TEXT NOT NULL,
    position_s REAL NOT NULL, title TEXT NOT NULL, artist TEXT,
    track_title TEXT, noted_at TEXT NOT NULL);
INSERT INTO meta VALUES ('schema_version', '6');
INSERT INTO stations (key, name, url, created_at) VALUES
  ('sunshine_live', 'SUNSHINE LIVE', 'https://example.invalid/live',
   '2026-10-01T10:00:00+02:00');
INSERT INTO jobs (id, name, station, start_time, duration_minutes, weekdays,
                  created_at) VALUES
  ('job_alt', 'Freitag Nacht', 'sunshine_live', '22:00', 300, 'fri',
   '2026-10-01T10:00:00+02:00');
INSERT INTO recordings (id, station_key, station_name, stream_url, state,
                        started_at, planned_end, ended_at, output_file,
                        size_bytes) VALUES
  ('rec_alt', 'sunshine_live', 'SUNSHINE LIVE', 'https://example.invalid/live',
   'completed', '2026-10-11T22:00:00+02:00', '2026-10-12T03:00:00+02:00',
   '2026-10-12T03:00:00+02:00', '/media/radio/alt.mp3', 360000000);
""")
verbindung.commit()
verbindung.close()

config.DB_FILE = alt
db._initialised = False
db.init()

with db.connect() as conn:
    stand = conn.execute(
        "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
pruefe(db.SCHEMA_VERSION == 7 and stand == "7", "Schema-Stand ist jetzt 7",
       f"-> {stand}")
job_alt = db.get_job("job_alt")
pruefe(job_alt is not None and job_alt["name"] == "Freitag Nacht"
       and job_alt["weekdays"] == ["fri"],
       "Vorhandener Zeitplan bleibt erhalten", f"-> {job_alt}")
pruefe(job_alt is not None and job_alt["cloud_auto"] is False,
       "Vorhandener Zeitplan laedt nicht ungefragt hoch")
rec_alt = db.get_recording("rec_alt")
pruefe(rec_alt is not None and rec_alt["size_bytes"] == 360000000
       and rec_alt["output_file"] == "/media/radio/alt.mp3",
       "Vorhandene Aufnahme bleibt erhalten", f"-> {rec_alt}")
pruefe(rec_alt is not None and rec_alt["cloud_state"] is None
       and "cloud_target" in rec_alt and "cloud_error" in rec_alt
       and "cloud_at" in rec_alt,
       "Cloud-Spalten nachgezogen und leer")
db.set_job_cloud_auto("job_alt", True)
pruefe(db.get_job("job_alt")["cloud_auto"] is True,
       "Schalter laesst sich auf der gehobenen Datenbank setzen")

db._initialised = False
try:
    db.init()
    zweiter_start = True
except Exception as err:
    zweiter_start = err
pruefe(zweiter_start is True, "Zweiter Start auf gehobener Datenbank laeuft durch",
       f"-> {zweiter_start}")

config.DB_FILE = neu_db
db._initialised = False
db.init()


print("\n=== 2. Optionen aus der Umgebung ===")

# Wie run.sh sie setzt - in einem eigenen Prozess, weil config sie nur beim
# Laden liest.
umgebung = dict(os.environ, CLOUD_TYPE="null", CLOUD_PATH="/Radio/Archiv/",
                CLOUD_REMOTE="gdrive:", CLOUD_AUTO="true",
                CLOUD_BWLIMIT_KBYTE="250")
ausgabe = subprocess.run(
    [sys.executable, "-c",
     "import json; from radio_recorder import config as c; "
     "print(json.dumps([c.CLOUD_TYPE, c.CLOUD_PATH, c.CLOUD_REMOTE, "
     "c.CLOUD_AUTO, c.CLOUD_BWLIMIT_KBYTE, str(c.CLOUD_CONFIG)]))"],
    cwd=str(PROJECT), env=umgebung, capture_output=True, text=True, timeout=60)
try:
    gelesen = json.loads(ausgabe.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    gelesen = [ausgabe.stdout, ausgabe.stderr]
pruefe(gelesen[0] == "aus", "\"null\" von bashio gilt als ausgeschaltet",
       f"-> {gelesen}")
pruefe(gelesen[1] == "Radio/Archiv", "Schraegstriche am Pfad fallen weg",
       f"-> {gelesen}")
pruefe(gelesen[2] == "gdrive", "Doppelpunkt am Remote faellt weg", f"-> {gelesen}")
pruefe(gelesen[3] is True and gelesen[4] == 250,
       "Schalter und Bandbreite werden gelesen", f"-> {gelesen}")
pruefe(gelesen[5].replace("\\", "/") == "/share/rclone.conf",
       "Eigene rclone.conf wird unter /share erwartet", f"-> {gelesen}")


print("\n=== 3. Ausgeschaltet ===")
app = web.create_app()
app.testing = True
client = app.test_client()

cloud_aus()
pruefe(not cloud.eingeschaltet() and not cloud.bereit()
       and cloud.fehlende_angaben() == [],
       "Vorgabe ist aus, ohne Fehlermeldung")
datei_aus = lege_aufnahme_an("aus1")
try:
    cloud.einreihen("aus1")
    abgelehnt = None
except ValueError as err:
    abgelehnt = str(err)
pruefe(abgelehnt is not None and "cloud_type" in abgelehnt,
       "Hochladen ohne Einrichtung wird mit Hinweis abgelehnt", f"-> {abgelehnt}")
pruefe(db.get_recording("aus1")["cloud_state"] is None,
       "Abgelehnte Aufnahme bleibt unvermerkt")
pruefe(cloud.nach_aufnahme("aus1") is False, "Nichts wird automatisch vorgemerkt")
seite = client.get("/").get_data(as_text=True)
pruefe("einschalten über die Add-on-Option" in seite,
       "Startseite sagt, wo man die Cloud einschaltet")
pruefe('name="cloud_auto"' not in seite,
       "Zeitplan-Formular zeigt keinen Cloud-Schalter, solange sie aus ist")
seite = client.get("/recordings").get_data(as_text=True)
pruefe("recordings/cloud/" not in seite, "Bibliothek zeigt keinen Cloud-Knopf")


print("\n=== 4. Fehlende Angaben ===")
cloud_aus()
config.CLOUD_TYPE = "webdav"
fehlt = cloud.fehlende_angaben()
pruefe(fehlt == ["cloud_url", "cloud_user", "cloud_password"],
       "WebDAV: Adresse, Benutzer und Passwort werden verlangt", f"-> {fehlt}")
pruefe(cloud.eingeschaltet() and not cloud.bereit(), "Eingeschaltet, aber nicht bereit")
try:
    cloud.einreihen("aus1")
    abgelehnt = None
except ValueError as err:
    abgelehnt = str(err)
pruefe(abgelehnt is not None and "cloud_password" in abgelehnt,
       "Hochladen nennt die fehlende Option", f"-> {abgelehnt}")
seite = client.get("/").get_data(as_text=True)
pruefe("eingeschaltet, aber es fehlt" in seite and "cloud_user" in seite,
       "Startseite zeigt, was fehlt")

config.CLOUD_TYPE = "s3"
fehlt = cloud.fehlende_angaben()
pruefe(len(fehlt) == 4 and any("Bucket" in f for f in fehlt),
       "S3: auch der Bucket wird verlangt", f"-> {fehlt}")

config.CLOUD_TYPE = "rclone"
config.CLOUD_REMOTE = "gdrive"
config.CLOUD_CONFIG = WORK / "gibt-es-nicht.conf"
fehlt = cloud.fehlende_angaben()
pruefe(len(fehlt) == 1 and "rclone.conf" in fehlt[0],
       "rclone: fehlende Konfigurationsdatei wird gemeldet", f"-> {fehlt}")

config.CLOUD_TYPE = "ftp"
fehlt = cloud.fehlende_angaben()
pruefe(len(fehlt) == 1 and "unbekannt" in fehlt[0],
       "Unbekannte Art wird abgelehnt statt still ignoriert", f"-> {fehlt}")


print("\n=== 5. Upload ueber WebDAV ===")
webdav_einrichten()
log_leeren()
pruefe(cloud.bereit(), "Mit allen Angaben bereit")
datei1 = lege_aufnahme_an("web1")
cloud.einreihen("web1")
eintrag = db.get_recording("web1")
pruefe(eintrag["cloud_state"] == "queued" and "WebDAV" in eintrag["cloud_target"],
       "Aufnahme steht in der Warteschlange", f"-> {eintrag['cloud_state']}")
try:
    cloud.einreihen("web1")
    doppelt = None
except ValueError as err:
    doppelt = str(err)
pruefe(doppelt is not None and "bereits" in doppelt,
       "Doppeltes Einreihen wird abgelehnt", f"-> {doppelt}")

pruefe(cloud.verarbeite_einen() is True, "Warteschlange wird abgearbeitet")
eintrag = db.get_recording("web1")
pruefe(eintrag["cloud_state"] == "done" and not eintrag["cloud_error"]
       and eintrag["cloud_at"],
       "Zustand danach: in der Cloud", f"-> {eintrag['cloud_state']} / {eintrag['cloud_error']}")
kopie = in_der_cloud(datei1)
pruefe(kopie.is_file() and kopie.read_bytes() == datei1.read_bytes(),
       "Die Datei ist in der Cloud angekommen", f"-> {kopie}")
pruefe(datei1.is_file(), "Das Original im Zielordner bleibt liegen")
pruefe(cloud.verarbeite_einen() is False, "Danach wartet nichts mehr")

konfig = config.DATA_DIR / "rclone-cloud.conf"
inhalt = konfig.read_bytes() if konfig.exists() else b""
text = inhalt.decode("utf-8", "replace")
pruefe("type = webdav" in text and "user = jens" in text
       and "url = https://cloud.example/remote.php/dav/files/jens" in text,
       "rclone-Konfiguration wird aus den Optionen erzeugt", f"-> {text!r}")
pruefe("pass = versteckt-" in text and PASSWORT not in text,
       "Passwort steht nur verschleiert in der Konfiguration")
pruefe(b"\r\n" not in inhalt, "Konfiguration hat Unix-Zeilenenden")

alle = aufrufe()
pruefe(any(a[:2] == ["obscure", "-"] for a in alle)
       and not any(PASSWORT in teil for a in alle for teil in a),
       "Passwort geht ueber die Standardeingabe, nie als Argument")
kopien = kopieraufrufe()
pruefe(len(kopien) == 1 and kopien[0][1] == str(datei1)
       and kopien[0][2] == "radio_recorder_cloud:Radio",
       "rclone kopiert die Datei in den gewaehlten Ordner", f"-> {kopien}")
pruefe(kopien and "--config" in kopien[0]
       and kopien[0][kopien[0].index("--config") + 1] == str(konfig),
       "rclone bekommt die erzeugte Konfiguration")
pruefe(kopien and kopien[0][kopien[0].index("--retries") + 1] == "1",
       "rclone wiederholt nicht selbst - das regelt das Add-on")
pruefe(kopien and "--bwlimit" not in kopien[0], "Ohne Angabe keine Drosselung")

config.CLOUD_URL = "https://jens:" + PASSWORT + "@cloud.example:8443/dav"
ziel = cloud.ziel_beschreibung()
pruefe(PASSWORT not in ziel and "jens" not in ziel and "cloud.example:8443" in ziel,
       "Zugangsdaten in der Adresse erscheinen nicht in der Anzeige", f"-> {ziel}")
webdav_einrichten()


print("\n=== 6. Drosselung und Zeitgrenze ===")
log_leeren()
config.CLOUD_BWLIMIT_KBYTE = 500
cloud.einreihen("web1")       # schon hochgeladen - erneut erlaubt
cloud.verarbeite_einen()
kopien = kopieraufrufe()
pruefe(kopien and kopien[0][kopien[0].index("--bwlimit") + 1] == "500k",
       "Bandbreite wird an rclone weitergegeben", f"-> {kopien}")
pruefe(db.get_recording("web1")["cloud_state"] == "done",
       "Erneuter Upload einer schon hochgeladenen Aufnahme klappt")
config.CLOUD_BWLIMIT_KBYTE = 0
pruefe(cloud._laufzeitgrenze(1000) == 600,
       "Kleine Datei: mindestens zehn Minuten Zeit")
pruefe(cloud._laufzeitgrenze(10 ** 12) == 12 * 3600,
       "Riesige Datei: hoechstens zwoelf Stunden")
ohne = cloud._laufzeitgrenze(400 * 1024 * 1024)
config.CLOUD_BWLIMIT_KBYTE = 20
mit = cloud._laufzeitgrenze(400 * 1024 * 1024)
config.CLOUD_BWLIMIT_KBYTE = 0
pruefe(mit > ohne, "Gedrosselt bekommt rclone mehr Zeit", f"-> {ohne} / {mit}")


print("\n=== 7. Fehlschlag ===")
cloud.VERSUCHE = 1
log_leeren()
os.environ["RR_FAKE_RCLONE"] = "fehler"
datei2 = lege_aufnahme_an("fehl1")
cloud.einreihen("fehl1")
cloud.verarbeite_einen()
eintrag = db.get_recording("fehl1")
pruefe(eintrag["cloud_state"] == "failed"
       and "401 Unauthorized" in (eintrag["cloud_error"] or ""),
       "Fehler wird am Rueckgabewert erkannt, Meldung von rclone bleibt",
       f"-> {eintrag['cloud_state']} / {eintrag['cloud_error']}")
pruefe(datei2.is_file() and eintrag["state"] == "completed",
       "Die Aufnahme selbst bleibt davon unberuehrt")
seite = client.get("/recordings").get_data(as_text=True)
pruefe("Upload fehlgeschlagen" in seite and "401 Unauthorized" in seite,
       "Bibliothek zeigt den Fehler")
pruefe("Erneut in die Cloud kopieren" in seite and "recordings/cloud/fehl1" in seite,
       "Bibliothek bietet einen neuen Versuch an")

os.environ["RR_FAKE_RCLONE"] = "still"
cloud.einreihen("fehl1")
cloud.verarbeite_einen()
eintrag = db.get_recording("fehl1")
pruefe(eintrag["cloud_state"] == "failed" and "Code 1" in (eintrag["cloud_error"] or ""),
       "Ohne Meldung von rclone wird der Rueckgabewert genannt",
       f"-> {eintrag['cloud_error']}")
os.environ["RR_FAKE_RCLONE"] = "ok"

datei3 = lege_aufnahme_an("weg1")
cloud.einreihen("weg1")
datei3.unlink()
cloud.verarbeite_einen()
eintrag = db.get_recording("weg1")
pruefe(eintrag["cloud_state"] == "failed"
       and "nicht vorhanden" in (eintrag["cloud_error"] or ""),
       "Zwischendurch geloeschte Datei fuehrt zu klarer Meldung",
       f"-> {eintrag['cloud_error']}")
try:
    cloud.einreihen("weg1")
    abgelehnt = None
except ValueError as err:
    abgelehnt = str(err)
pruefe(abgelehnt is not None and "nicht mehr vorhanden" in abgelehnt,
       "Ohne Datei wird gar nicht erst eingereiht", f"-> {abgelehnt}")


print("\n=== 8. Wiederholung ===")
cloud.VERSUCHE = 3
log_leeren()
os.environ["RR_FAKE_RCLONE"] = "einmal_fehler"
datei4 = lege_aufnahme_an("wdh1")
cloud.einreihen("wdh1")
cloud.verarbeite_einen()
os.environ["RR_FAKE_RCLONE"] = "ok"
eintrag = db.get_recording("wdh1")
pruefe(eintrag["cloud_state"] == "done" and len(kopieraufrufe()) == 2,
       "Nach einem Fehlversuch klappt der zweite",
       f"-> {eintrag['cloud_state']}, {len(kopieraufrufe())} Aufrufe")
pruefe(in_der_cloud(datei4).is_file(), "Datei ist nach der Wiederholung da")


print("\n=== 9. Neustart ===")
datei5 = lege_aufnahme_an("neu1")
db.update_recording("neu1", cloud_state="uploading")
zurueck = db.cloud_unterbrochene_freigeben()
pruefe(zurueck == 1 and db.get_recording("neu1")["cloud_state"] == "queued",
       "Unterbrochener Upload kommt zurueck in die Warteschlange",
       f"-> {zurueck}")

# Wird das Add-on waehrend der Pause zwischen zwei Versuchen beendet, ist
# das kein Fehlschlag - nach dem Neustart geht es weiter.
cloud.VERSUCHE = 2
os.environ["RR_FAKE_RCLONE"] = "fehler"
cloud._halt.set()
cloud.lade_hoch(db.get_recording("neu1"))
cloud._halt.clear()
os.environ["RR_FAKE_RCLONE"] = "ok"
cloud.VERSUCHE = 3
eintrag = db.get_recording("neu1")
pruefe(eintrag["cloud_state"] == "queued",
       "Beim Beenden abgebrochener Upload bleibt vorgemerkt",
       f"-> {eintrag['cloud_state']}")
cloud.verarbeite_einen()
pruefe(db.get_recording("neu1")["cloud_state"] == "done",
       "Nach dem Neustart wird er nachgeholt")

# Der echte Thread: startet, arbeitet ab, laesst sich beenden.
datei6 = lege_aufnahme_an("thr1")
cloud.start()
cloud.einreihen("thr1")
grenze = time.monotonic() + 20
while time.monotonic() < grenze and db.get_recording("thr1")["cloud_state"] != "done":
    time.sleep(0.2)
pruefe(db.get_recording("thr1")["cloud_state"] == "done",
       "Hintergrund-Thread arbeitet die Warteschlange ab")
cloud.shutdown()
cloud._thread.join(timeout=10)
pruefe(not cloud._thread.is_alive(), "Hintergrund-Thread laesst sich beenden")
cloud._halt.clear()


print("\n=== 10. Automatisch nach der Aufnahme ===")
webdav_einrichten()
mit_cloud = db.add_job(name="Mit Cloud", station="sunshine_live",
                       start_time="22:00", duration_minutes=60,
                       weekdays=["fri"], cloud_auto=True)
ohne_cloud = db.add_job(name="Ohne Cloud", station="sunshine_live",
                        start_time="23:00", duration_minutes=60,
                        weekdays=["fri"])
gespielte_aufnahme("auto_mit", job_id=mit_cloud)
gespielte_aufnahme("auto_ohne", job_id=ohne_cloud)
Recorder().resume_pending()
mit = warte_auf_zustand("auto_mit")
ohne = warte_auf_zustand("auto_ohne")
pruefe(mit["state"] == "completed" and mit["cloud_state"] == "queued",
       "Zeitplan mit Cloud-Schalter: Aufnahme wird vorgemerkt",
       f"-> {mit['state']} / {mit['cloud_state']}")
pruefe(ohne["state"] == "completed" and ohne["cloud_state"] is None,
       "Zeitplan ohne Schalter: nichts wird hochgeladen",
       f"-> {ohne['state']} / {ohne['cloud_state']}")

config.CLOUD_AUTO = True
gespielte_aufnahme("auto_alle")
Recorder().resume_pending()
alle_auto = warte_auf_zustand("auto_alle")
pruefe(alle_auto["cloud_state"] == "queued",
       "Option cloud_auto: auch manuelle Aufnahmen werden vorgemerkt",
       f"-> {alle_auto['cloud_state']}")

config.CLOUD_PASSWORD = ""
gespielte_aufnahme("auto_halb", job_id=mit_cloud)
Recorder().resume_pending()
halb = warte_auf_zustand("auto_halb")
pruefe(halb["state"] == "completed" and halb["cloud_state"] is None
       and Path(halb["output_file"] or "").is_file(),
       "Unvollstaendige Einrichtung bremst die Aufnahme nicht aus",
       f"-> {halb['state']} / {halb['cloud_state']} / {halb['error']}")
webdav_einrichten()
while cloud.verarbeite_einen():
    pass
pruefe(db.get_recording("auto_mit")["cloud_state"] == "done"
       and db.get_recording("auto_alle")["cloud_state"] == "done",
       "Vorgemerkte Aufnahmen landen in der Cloud")


print("\n=== 11. Oberflaeche ===")
webdav_einrichten()
datei7 = lege_aufnahme_an("ui1")
antwort = client.post("/recordings/cloud/ui1")
pruefe(antwort.status_code == 302 and db.get_recording("ui1")["cloud_state"] == "queued",
       "Knopf in der Bibliothek reiht die Aufnahme ein")
seite = client.get("/recordings").get_data(as_text=True)
pruefe("☁ wartet" in seite, "Bibliothek zeigt den Stand")
pruefe("recordings/cloud/ui1" not in seite,
       "Waehrend sie wartet, gibt es keinen zweiten Knopf")
pruefe("recordings/cloud/web1" in seite and "Erneut in die Cloud kopieren" in seite,
       "Hochgeladene Aufnahme laesst sich erneut senden")
antwort = client.post("/recordings/cloud/gibtsnicht", follow_redirects=True)
pruefe("gibt es nicht mehr" in antwort.get_data(as_text=True),
       "Unbekannte Aufnahme gibt eine Meldung")

db.update_recording("ui1", cloud_state="uploading")
client.post("/recordings/delete/ui1")
pruefe(db.get_recording("ui1") is not None and datei7.is_file(),
       "Waehrend des Uploads laesst sich die Aufnahme nicht loeschen")
db.update_recording("ui1", cloud_state="done")

seite = client.get("/").get_data(as_text=True)
pruefe("WebDAV https://cloud.example" in seite, "Startseite nennt das Ziel")
pruefe('name="cloud_auto"' in seite, "Zeitplan-Formular hat den Cloud-Schalter")

client.post("/schedule/add", data={
    "name": "Formular", "station": "sunshine_live", "start_time": "20:00",
    "modus": "dauer", "hours": "1", "minutes": "0", "weekday": ["sat"],
    "lead_in": "0", "lead_out": "0", "cloud_auto": "1"})
formular = [j for j in db.list_jobs() if j["name"] == "Formular"]
pruefe(formular and formular[0]["cloud_auto"] is True,
       "Zeitplan aus dem Formular merkt sich den Schalter")
if formular:
    client.post(f"/schedule/cloud/{formular[0]['id']}")
    pruefe(db.get_job(formular[0]["id"])["cloud_auto"] is False,
           "Schalter am gespeicherten Zeitplan laesst sich umlegen")


print("\n=== 12. Eigene rclone-Konfiguration ===")
# /share ist nur lesend eingebunden. rclone muss erneuerte Zugangsschluessel
# aber zurueckschreiben koennen, sonst verfaellt die Anmeldung bei OneDrive
# und Co. - deshalb arbeitet das Add-on mit einer Kopie in /data.
cloud_aus()
vorlage = WORK / "share" / "rclone.conf"
vorlage.parent.mkdir(parents=True, exist_ok=True)
with open(vorlage, "w", encoding="utf-8", newline="") as datei:
    datei.write("[onedrive]\ntype = onedrive\ntoken = alt\n")
config.CLOUD_TYPE = "rclone"
config.CLOUD_REMOTE = "onedrive"
config.CLOUD_PATH = "Radiotest"
config.CLOUD_CONFIG = vorlage
kopie_conf = config.DATA_DIR / "rclone-eigen.conf"
pruefe(cloud.bereit(), "Mit Remote und vorhandener rclone.conf bereit")

log_leeren()
os.environ["RR_FAKE_RCLONE_ERNEUERN"] = "1"
datei8 = lege_aufnahme_an("eig1")
cloud.einreihen("eig1")
cloud.verarbeite_einen()
del os.environ["RR_FAKE_RCLONE_ERNEUERN"]
kopien = kopieraufrufe()
pruefe(db.get_recording("eig1")["cloud_state"] == "done"
       and in_der_cloud(datei8, remote="onedrive", pfad="Radiotest").is_file(),
       "Upload ueber das eigene Remote klappt",
       f"-> {db.get_recording('eig1')['cloud_state']} / {db.get_recording('eig1')['cloud_error']}")
pruefe(kopien and kopien[0][2] == "onedrive:Radiotest"
       and kopien[0][kopien[0].index("--config") + 1] == str(kopie_conf),
       "rclone arbeitet mit der Kopie in /data, nicht mit der Vorlage",
       f"-> {kopien}")
pruefe(vorlage.read_text(encoding="utf-8") == "[onedrive]\ntype = onedrive\ntoken = alt\n",
       "Die Vorlage bleibt unberuehrt")
pruefe("token = neu" in kopie_conf.read_text(encoding="utf-8"),
       "Erneuerter Schluessel landet in der Kopie")

cloud.einreihen("eig1")
cloud.verarbeite_einen()
pruefe("token = neu" in kopie_conf.read_text(encoding="utf-8"),
       "Naechster Upload ueberschreibt den erneuerten Schluessel nicht")

with open(vorlage, "w", encoding="utf-8", newline="") as datei:
    datei.write("[onedrive]\ntype = onedrive\ntoken = frisch\n")
cloud.einreihen("eig1")
cloud.verarbeite_einen()
pruefe("token = frisch" in kopie_conf.read_text(encoding="utf-8"),
       "Neu eingerichtete Vorlage wird uebernommen")
cloud_aus()


print("\n=== 13. Add-on-Dateien ===")
# Der Container laesst sich hier nicht bauen. Was dort zusammenpassen muss,
# wird wenigstens in den Dateien geprueft.
yaml_text = (PROJECT / "config.yaml").read_text(encoding="utf-8")
pruefe("cloud_password: password?" in yaml_text,
       "Passwort ist im Schema als password markiert - HA zeigt es verdeckt")
pruefe(f'version: "{__version__}"' in yaml_text,
       "Fassung in config.yaml und im Paket stimmt ueberein", f"-> {__version__}")
pruefe("type: share" in yaml_text, "/share ist eingebunden, fuer eine eigene rclone.conf")
for zeile in ("cloud_type: list(aus|webdav|s3|rclone)", 'cloud_type: "aus"',
              "cloud_auto: false"):
    pruefe(zeile in yaml_text, f"config.yaml enthaelt {zeile}")

run_text = (PROJECT / "run.sh").read_text(encoding="utf-8")
for name in ("CLOUD_TYPE", "CLOUD_AUTO", "CLOUD_URL", "CLOUD_USER",
             "CLOUD_PASSWORD", "CLOUD_PATH", "CLOUD_REMOTE", "CLOUD_CONFIG",
             "CLOUD_BWLIMIT_KBYTE"):
    pruefe(name in run_text and hasattr(config, name),
           f"{name} wird von run.sh gesetzt und von config gelesen")
docker_text = (PROJECT / "Dockerfile").read_text(encoding="utf-8")
pruefe("rclone" in docker_text, "Dockerfile installiert rclone")


cloud.shutdown()
print("\n" + "=" * 62)
print(f"Bestanden: {len(bestanden)}   Fehlgeschlagen: {len(fehlgeschlagen)}")
for eintrag in fehlgeschlagen:
    print(f"  - {eintrag}")
print("=" * 62)
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if fehlgeschlagen else 0)
