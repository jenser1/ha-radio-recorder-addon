"""Rauchtest Phase 3, Stufe 1: Titelmeldungen der Sender auswerten.

Braucht kein ffmpeg - der Aufruf wird durch tests/fake_ffmpeg.py ersetzt.
Aufruf aus dem Projektordner:  python tests/test_phase3.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent / "radio_recorder"

WORK = Path(tempfile.mkdtemp(prefix="rr_p3_"))
os.environ["DATA_DIR"] = str(WORK / "data")
os.environ["OUTPUT_DIR"] = str(WORK / "out")
os.environ["TZ"] = "Europe/Berlin"
sys.path.insert(0, str(PROJECT))

from radio_recorder import config, db, metadata, web, zeit    # noqa: E402

config.FFMPEG = [sys.executable, str(HERE / "fake_ffmpeg.py")]

bestanden, fehlgeschlagen = [], []


def pruefe(bedingung, beschreibung, detail=""):
    if bedingung:
        bestanden.append(beschreibung)
        print(f"  OK   {beschreibung}")
    else:
        fehlgeschlagen.append(f"{beschreibung} {detail}".strip())
        print(f"  FEHL {beschreibung} {detail}")


print("\n=== 1. Titelzeilen erkennen ===")

# Die Schreibweise haengt von der ffmpeg-Fassung ab - alle bekannten Formen
# muessen erkannt werden.
for zeile, erwartet in (
        ("[http @ 0x55] Metadata update for StreamTitle: Mr. Oizo - Flat Beat",
         "Mr. Oizo - Flat Beat"),
        ("    StreamTitle     : Paul Kalkbrenner - Sky and Sand",
         "Paul Kalkbrenner - Sky and Sand"),
        ("StreamTitle='Scooter - How Much Is The Fish';",
         "Scooter - How Much Is The Fish"),
        ('StreamTitle="Anyma - Consciousness";', "Anyma - Consciousness"),
        ("  StreamTitle: Nur Ein Titel", "Nur Ein Titel"),
):
    ergebnis = metadata.titel_aus_zeile(zeile)
    pruefe(ergebnis == erwartet, f"erkannt: {erwartet}", f"-> {ergebnis!r}")

for zeile in ("Eine ganz normale Zeile",
              "StreamTitle=''",
              "StreamTitle: ",
              "StreamTitle     : -",
              ""):
    pruefe(metadata.titel_aus_zeile(zeile) is None,
           f"kein Titel in {zeile!r}",
           f"-> {metadata.titel_aus_zeile(zeile)!r}")


print("\n=== 2. Interpret und Titel trennen ===")

for eingabe, erwartet in (
        ("Mr. Oizo - Flat Beat", ("Mr. Oizo", "Flat Beat")),
        ("Anyma – Consciousness", ("Anyma", "Consciousness")),
        ("Artist — Titel", ("Artist", "Titel")),
        ("Nur ein Titel ohne Trenner", (None, "Nur ein Titel ohne Trenner")),
        ("- Titel", (None, "- Titel")),
        ("", (None, "")),
        # Der erste Trenner gilt, damit Bindestriche im Titel heil bleiben.
        ("AC/DC - T.N.T. - Live", ("AC/DC", "T.N.T. - Live")),
):
    ergebnis = metadata.zerlege_titel(eingabe)
    pruefe(ergebnis == erwartet, f"{eingabe!r} wird zu {erwartet}",
           f"-> {ergebnis}")


print("\n=== 3. Sender pruefen ===")

db.init()
key = db.add_station(name="Testsender", url="https://example.invalid/strom")
station = db.get_station(key)
pruefe(station["metadata_state"] is None,
       "Neuer Sender gilt zunaechst als ungeprueft",
       f"-> {station['metadata_state']}")

os.environ["RR_FAKE_TITEL"] = "Artist A - Lied Eins|Artist B - Lied Zwei"
befund = metadata.pruefe_sender("https://example.invalid/strom", dauer=2)
pruefe(befund["titel"] == ["Artist A - Lied Eins", "Artist B - Lied Zwei"],
       "Gemeldete Titel werden in der Reihenfolge erfasst",
       f"-> {befund['titel']}")
pruefe(befund["fehler"] is None, "Kein Fehler gemeldet", f"-> {befund['fehler']}")
pruefe(all("StreamTitle" in z for z in befund["rohzeilen"]),
       "Rohzeilen werden zum Nachsehen festgehalten",
       f"-> {befund['rohzeilen']}")

# Derselbe Titel mehrfach hintereinander ist kein Liedwechsel.
os.environ["RR_FAKE_TITEL"] = "Gleicher Titel|Gleicher Titel|Anderer Titel"
befund = metadata.pruefe_sender("https://example.invalid/strom", dauer=2)
pruefe(befund["titel"] == ["Gleicher Titel", "Anderer Titel"],
       "Wiederholungen werden zusammengefasst", f"-> {befund['titel']}")

# Windows reicht leere Variablen nicht weiter - daher das Wort "KEINE".
os.environ["RR_FAKE_TITEL"] = "KEINE"
befund = metadata.pruefe_sender("https://example.invalid/strom", dauer=2)
pruefe(befund["titel"] == [], "Sender ohne Titel liefert leere Liste",
       f"-> {befund['titel']}")

os.environ["RR_FAKE_TITEL"] = "FEHLER"
befund = metadata.pruefe_sender("https://example.invalid/strom", dauer=2)
pruefe(befund["fehler"] and "404" in befund["fehler"],
       "Nicht erreichbarer Sender meldet den Grund", f"-> {befund['fehler']}")

merker = config.FFMPEG
config.FFMPEG = ["gibtesnicht_ffmpeg_xyz"]
befund = metadata.pruefe_sender("https://example.invalid/strom", dauer=2)
pruefe(befund["fehler"] and "ffmpeg" in befund["fehler"],
       "Fehlendes ffmpeg wird gemeldet statt zu stuerzen",
       f"-> {befund['fehler']}")
config.FFMPEG = merker


print("\n=== 4. Pruefung ueber die Oberflaeche ===")

app = web.create_app()
app.config["TESTING"] = True
client = app.test_client()

os.environ["RR_FAKE_TITEL"] = "Artist A - Lied Eins|Artist B - Lied Zwei"
client.post(f"/stations/metadata/{key}")
station = db.get_station(key)
pruefe(station["metadata_state"] == "ok", "Zustand wird auf ok gesetzt",
       f"-> {station['metadata_state']}")
pruefe(station["metadata_checked_at"], "Zeitpunkt der Pruefung wird vermerkt")
pruefe("StreamTitle" in (station["metadata_sample"] or ""),
       "Rohzeilen werden gespeichert", f"-> {station['metadata_sample']!r}")

seite = client.get("/stations").get_data(as_text=True)
pruefe("Titelerkennung möglich" in seite, "Ergebnis erscheint in der Liste")
pruefe("Was der Sender meldet" in seite, "Rohzeilen sind aufklappbar")

# Windows reicht leere Variablen nicht weiter - daher das Wort "KEINE".
os.environ["RR_FAKE_TITEL"] = "KEINE"
client.post(f"/stations/metadata/{key}")
pruefe(db.get_station(key)["metadata_state"] == "keine",
       "Sender ohne Titel wird als 'keine' vermerkt",
       f"-> {db.get_station(key)['metadata_state']}")
pruefe("keine Titel gemeldet" in client.get("/stations").get_data(as_text=True),
       "Das steht auch in der Liste")

os.environ["RR_FAKE_TITEL"] = "FEHLER"
client.post(f"/stations/metadata/{key}")
pruefe(db.get_station(key)["metadata_state"] == "fehler",
       "Fehlgeschlagene Pruefung wird vermerkt")

antwort = client.post("/stations/metadata/gibtesnicht")
pruefe(antwort.status_code in (302, 303),
       "Unbekannter Sender fuehrt nicht zum Absturz",
       f"-> {antwort.status_code}")

with db.connect() as conn:
    stand = conn.execute(
        "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
pruefe(stand == str(db.SCHEMA_VERSION),
       f"Schema-Stand ist {db.SCHEMA_VERSION}", f"-> {stand}")


print("\n=== 5. Titel waehrend der Aufnahme mitschreiben ===")

import time                                                    # noqa: E402
from radio_recorder.recorder import Recorder                    # noqa: E402

config.SEGMENT_MINUTES = 0.05          # 3 Sekunden je Segment
config.WORK_DIR.mkdir(parents=True, exist_ok=True)
config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def warte_auf_zustand(rid, timeout=40):
    grenze = time.monotonic() + timeout
    while time.monotonic() < grenze:
        eintrag = db.get_recording(rid)
        if eintrag and eintrag["state"] != "running":
            return eintrag
        time.sleep(0.3)
    return db.get_recording(rid)


sender = db.add_station(name="Marken-Test", url="https://example.invalid/marken")
os.environ["RR_FAKE_TITEL"] = "Erster - Titel|Zweiter - Titel|Dritter - Titel"
os.environ["RR_FAKE_TITEL_ABSTAND"] = "2"

rec = Recorder()
rid = rec.start(sender, duration_minutes=1, label="Marken")
time.sleep(7)
rec.stop(rid)
warte_auf_zustand(rid)

marken = db.list_track_marks(rid)
pruefe(len(marken) == 3, "Alle drei Titel wurden vermerkt",
       f"-> {[m['title'] for m in marken]}")
pruefe([m["title"] for m in marken] ==
       ["Erster - Titel", "Zweiter - Titel", "Dritter - Titel"],
       "Reihenfolge stimmt")
pruefe(marken and marken[0]["artist"] == "Erster"
       and marken[0]["track_title"] == "Titel",
       "Interpret und Titel wurden getrennt",
       f"-> {marken[0] if marken else None}")
pruefe(all(m["position_s"] >= 0 for m in marken), "Positionen sind nicht negativ")
pruefe([m["position_s"] for m in marken]
       == sorted(m["position_s"] for m in marken),
       "Positionen steigen an",
       f"-> {[round(m['position_s'], 1) for m in marken]}")
pruefe(marken and marken[-1]["position_s"] > marken[0]["position_s"] + 1,
       "Abstaende bilden den zeitlichen Verlauf ab",
       f"-> {[round(m['position_s'], 1) for m in marken]}")


print("\n--- Fortsetzung nach Unterbrechung ---")
# Der springende Punkt: nach einem Neustart duerfen die Marken nicht wieder
# bei null anfangen, sonst zeigen sie spaeter auf die falsche Stelle.
os.environ["RR_FAKE_TITEL"] = "Vor Neustart - Eins"
os.environ["RR_FAKE_TITEL_ABSTAND"] = "0.5"
rec2 = Recorder()
rid2 = rec2.start(sender, duration_minutes=1, label="Neustart")
time.sleep(5)
rec2.shutdown(timeout=8)

vorher = db.list_track_marks(rid2)
pruefe(len(vorher) == 1, "Titel aus dem ersten Abschnitt vermerkt",
       f"-> {[m['title'] for m in vorher]}")

os.environ["RR_FAKE_TITEL"] = "Nach Neustart - Zwei"
rec3 = Recorder()
rec3.resume_pending()
time.sleep(5)
rec3.stop(rid2)
warte_auf_zustand(rid2)

nachher = db.list_track_marks(rid2)
pruefe(len(nachher) == 2, "Auch der Titel nach dem Neustart wurde vermerkt",
       f"-> {[m['title'] for m in nachher]}")
pruefe(len(nachher) == 2 and nachher[1]["position_s"] > nachher[0]["position_s"],
       "Die Marke nach dem Neustart liegt spaeter, nicht wieder bei null",
       f"-> {[round(m['position_s'], 1) for m in nachher]}")
pruefe(len(nachher) == 2 and nachher[1]["position_s"] >= 3,
       "Der Vorlauf der schon aufgenommenen Segmente wurde mitgezaehlt",
       f"-> {round(nachher[1]['position_s'], 1) if len(nachher) == 2 else None}")

os.environ["RR_FAKE_TITEL"] = "KEINE"
os.environ["RR_FAKE_TITEL_ABSTAND"] = "1.0"


print("\n--- Anzeige in der Bibliothek ---")
seite = client.get("/recordings").get_data(as_text=True)
pruefe("Titel erkannt" in seite, "Titelliste erscheint in der Bibliothek")
pruefe("Erster" in seite, "Die Titel stehen darin")
# Im Abstand von zwei Sekunden gemeldet - das sind keine Lieder.
pruefe("aussortiert" in seite and "zu kurz" in seite,
       "Zu kurze Abschnitte erscheinen als aussortiert")

db.delete_recording(rid)
pruefe(db.list_track_marks(rid) == [],
       "Beim Loeschen einer Aufnahme verschwinden auch ihre Marken")


print("\n--- Pufferstoss beim Verbinden ---")
# Server schicken beim Verbinden einige Sekunden am Stueck. ffmpeg ist
# dadurch frueher mit seiner Spielzeit durch als die Uhr - das darf nicht
# als Abbruch gelten und keinen neuen Verbindungsversuch ausloesen.
os.environ["RR_FAKE_VORLAUF"] = "55"
rec4 = Recorder()
begonnen = time.monotonic()
rid3 = rec4.start(sender, duration_minutes=1, label="Pufferstoss")
fertig = warte_auf_zustand(rid3, timeout=40)
gebraucht = time.monotonic() - begonnen
del os.environ["RR_FAKE_VORLAUF"]

pruefe(fertig["state"] == "completed",
       "Aufnahme gilt als regulaer beendet", f"-> {fertig['state']}")
pruefe(fertig["retry_count"] == 0,
       "Kein ueberfluessiger Verbindungsversuch am Ende",
       f"-> {fertig['retry_count']} Versuche")
pruefe(gebraucht < 30,
       "Beendet sich, sobald die Spielzeit erreicht ist",
       f"-> nach {gebraucht:.1f}s statt erst nach 60s")
pruefe(not fertig["error"], "Kein Fehler vermerkt", f"-> {fertig['error']!r}")


print("\n=== 6. Fortschrittszeilen auswerten ===")
from radio_recorder import recorder as recorder_modul            # noqa: E402

for schluessel, wert, erwartet in (
        ("out_time_us", "5000000", 5.0),
        ("out_time_us", "1234567", 1.234567),
        ("out_time", "01:02:03.500000", 3723.5),
        ("out_time", "00:00:00.000000", 0.0),
        ("out_time_us", "N/A", None),
        ("out_time", "", None),
        ("out_time_us", "kaputt", None),
        # Wird bewusst uebergangen: manche ffmpeg-Fassungen liefern dort
        # Mikrosekunden statt Millisekunden.
        ("out_time_ms", "5000", None),
):
    ergebnis = recorder_modul._progress_sekunden(schluessel, wert)
    passt = (ergebnis is None and erwartet is None) or (
        ergebnis is not None and erwartet is not None
        and abs(ergebnis - erwartet) < 0.0001)
    pruefe(passt, f"{schluessel}={wert!r} ergibt {erwartet}", f"-> {ergebnis}")


print("\n=== 7. Titel aussortieren ===")
from radio_recorder import titelfilter                             # noqa: E402


def marken_aus(liste):
    """Marken wie aus der Datenbank, aus (Position, Rohtext)."""
    ergebnis = []
    for position, roh in liste:
        interpret, titel = metadata.zerlege_titel(roh)
        ergebnis.append({"position_s": position, "title": roh,
                         "artist": interpret, "track_title": titel})
    return ergebnis


def urteile(beurteilt):
    return [m["urteil"] for m in beurteilt]


# Die Classics-Aufnahme vom 11.10.2026, so wie sie gemeldet wurde.
classics = marken_aus([
    (0, "sunshine live - Classics"),
    (20, "Terry Bones - Dreaming (DJ Kalpa Mix)"),
    (140, "DJ Quicksilver - Ameno [2000] (Club Mix)"),
    (588, "Veracocha - Carte Blanche (Original Mix)"),
    (1005, "Scooter - Jump That Rock (Whatever You Want)"),
    (1347, "Tek Room - Fox 2000 (Extended Version)"),
])
beurteilt = titelfilter.beurteile(classics, sendername="Sunshine-Live Classics",
                                  gesamtdauer=1740)
pruefe(urteile(beurteilt) == ["kennung"] + ["lied"] * 5,
       "Classics: Senderkennung raus, fuenf Lieder bleiben",
       f"-> {urteile(beurteilt)}")
pruefe(len(titelfilter.lieder(beurteilt)) == 5, "lieder() liefert genau die fuenf")
pruefe("urteil" not in classics[0],
       "Die Rohliste bleibt unveraendert, beurteilt werden Kopien")
pruefe(beurteilt[0]["grund"], "Aussortiertes traegt eine Begruendung",
       f"-> {beurteilt[0]['grund']!r}")

for sender, roh, erwartet, beschreibung in (
        ("SUNSHINE LIVE", "SUNSHINE LIVE - Simulcast", "kennung",
         "Simulcast-Kennung des Hauptstroms"),
        ("Sunshine Live", "SUNSHINE-LIVE", "kennung",
         "Schreibweise und Bindestrich spielen keine Rolle"),
        ("Sunshine Live", "Live - Lightning Crashes", "lied",
         "Die Band 'Live' bleibt ein Lied"),
        ("Scooter Radio", "Scooter - Jump That Rock", "lied",
         "Interpret mit Namen des Senders bleibt ein Lied"),
        ("Sunshine Live", "Werbung", "werbung", "'Werbung' wird erkannt"),
        ("Sunshine Live", "SUNSHINE LIVE - Werbung", "werbung",
         "Werbung mit Sendername wird erkannt"),
        ("Sunshine Live", "Commercial Love - Every Day", "lied",
         "Ein Werbewort allein macht kein Lied zur Werbung"),
        ("Sunshine Live", "Dance Department - Armin Van Buuren", "lied",
         "Sendungsname ohne Muster ist nicht erkennbar"),
):
    ergebnis = titelfilter.beurteile(marken_aus([(0, roh)]), sendername=sender)
    pruefe(urteile(ergebnis) == [erwartet], f"{beschreibung}",
           f"-> {urteile(ergebnis)} fuer {roh!r} bei {sender!r}")

ergebnis = titelfilter.beurteile(
    marken_aus([(0, "Dance Department - Armin Van Buuren")]),
    sendername="Sunshine Live", muster=["dance department"])
pruefe(urteile(ergebnis) == ["sendung"],
       "Mit Muster wird der Sendungsname erkannt, ohne Ruecksicht auf Grossschreibung",
       f"-> {urteile(ergebnis)}")
pruefe("Dance Department" not in ergebnis[0]["grund"]
       and "dance department" in ergebnis[0]["grund"],
       "Die Begruendung nennt das Muster", f"-> {ergebnis[0]['grund']!r}")

# Bei Liveprogramm steht dieselbe Meldung stundenlang da.
ergebnis = titelfilter.beurteile(marken_aus([
    (0, "Dance Department - Armin Van Buuren"),
    (3600, "DANCE DEPARTMENT - Armin van Buuren"),
]), sendername="Sunshine Live")
pruefe(urteile(ergebnis) == ["lied", "dublette"],
       "Wiederholung derselben Meldung zaehlt nicht doppelt",
       f"-> {urteile(ergebnis)}")

print("\n--- Mindestdauer ---")
ergebnis = titelfilter.beurteile(marken_aus([
    (0, "A - Eins"), (59, "B - Zwei"), (119, "C - Drei"), (500, "D - Vier"),
]), sendername="Testsender")
pruefe(urteile(ergebnis)[:3] == ["kurz", "lied", "lied"],
       "Unter 60 Sekunden kein Lied, genau 60 schon", f"-> {urteile(ergebnis)}")
pruefe(urteile(ergebnis)[3] == "lied",
       "Letzte Marke ohne bekannte Gesamtdauer bleibt verschont",
       f"-> {urteile(ergebnis)}")
ergebnis = titelfilter.beurteile(marken_aus([(0, "A - Eins"), (500, "D - Vier")]),
                                 sendername="Testsender", gesamtdauer=530)
pruefe(urteile(ergebnis) == ["lied", "kurz"],
       "Letzte Marke zaehlt bis zum Ende der Aufnahme", f"-> {urteile(ergebnis)}")
ergebnis = titelfilter.beurteile(marken_aus([(0, "A - Eins"), (30, "Werbung")]),
                                 sendername="Testsender", gesamtdauer=600)
pruefe(urteile(ergebnis) == ["kurz", "werbung"],
       "Inhaltlicher Grund geht vor der Dauer", f"-> {urteile(ergebnis)}")
pruefe(titelfilter.beurteile([], sendername="X") == [], "Leere Liste bleibt leer")

pruefe(titelfilter.muster_aus_text("  Dance Department \r\n\n Werbung\n") ==
       ["Dance Department", "Werbung"],
       "Muster: eine Zeile je Eintrag, Leerzeilen fallen weg")


print("\n=== 8. Datenbank von Stand 5 auf Stand 6 heben ===")
import sqlite3                                                     # noqa: E402

# Stand 5, so wie er bei Anwendern mit echten Zeitplaenen und Aufnahmen liegt.
neu_db = config.DB_FILE
alt = WORK / "data" / "stand5.db"
verbindung = sqlite3.connect(str(alt))
verbindung.executescript("""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE stations (
    key TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
    ext TEXT NOT NULL DEFAULT 'mp3', codec TEXT,
    bitrate_kbps INTEGER NOT NULL DEFAULT 192, country TEXT, homepage TEXT,
    source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL,
    checked_at TEXT, metadata_state TEXT, metadata_checked_at TEXT,
    metadata_sample TEXT);
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
INSERT INTO meta VALUES ('schema_version', '5');
INSERT INTO stations (key, name, url, created_at, metadata_state) VALUES
  ('classics', 'Sunshine-Live Classics', 'https://example.invalid/classics',
   '2026-10-01T10:00:00+02:00', 'ok');
INSERT INTO jobs (id, name, station, start_time, duration_minutes, weekdays,
                  created_at) VALUES
  ('job_alt', 'Freitag Nacht', 'classics', '22:00', 300, 'fri',
   '2026-10-01T10:00:00+02:00');
INSERT INTO recordings (id, station_key, station_name, stream_url, state,
                        started_at, planned_end, ended_at) VALUES
  ('rec_alt', 'classics', 'Sunshine-Live Classics',
   'https://example.invalid/classics', 'completed',
   '2026-10-11T14:13:07+02:00', '2026-10-11T14:42:07+02:00',
   '2026-10-11T14:42:07+02:00');
INSERT INTO track_marks (recording_id, position_s, title, artist, track_title,
                         noted_at) VALUES
  ('rec_alt', 0, 'sunshine live - Classics', 'sunshine live', 'Classics',
   '2026-10-11T14:13:07+02:00'),
  ('rec_alt', 20, 'Terry Bones - Dreaming', 'Terry Bones', 'Dreaming',
   '2026-10-11T14:13:27+02:00');
""")
verbindung.commit()
verbindung.close()

config.DB_FILE = alt
db._initialised = False
db.init()

with db.connect() as conn:
    stand = conn.execute(
        "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
pruefe(stand == "6", "Schema-Stand ist jetzt 6", f"-> {stand}")
sender_alt = db.get_station("classics")
pruefe(sender_alt is not None and sender_alt["metadata_state"] == "ok",
       "Vorhandener Sender bleibt samt Pruefergebnis erhalten", f"-> {sender_alt}")
pruefe(sender_alt is not None and "title_filters" in sender_alt
       and sender_alt["title_filters"] is None,
       "Spalte fuer Muster wurde nachgezogen und ist leer")
pruefe(len(db.list_jobs()) == 1 and db.list_jobs()[0]["name"] == "Freitag Nacht",
       "Vorhandener Zeitplan bleibt erhalten")
pruefe(db.get_recording("rec_alt") is not None
       and len(db.list_track_marks("rec_alt")) == 2,
       "Vorhandene Aufnahme samt Marken bleibt erhalten")
seite = client.get("/recordings").get_data(as_text=True)
pruefe("1 Titel erkannt · 1 aussortiert" in seite,
       "Alte Marken werden ohne Nacharbeit beurteilt")

db._initialised = False
db.init()
pruefe(len(db.list_stations()) == 1 and len(db.list_track_marks("rec_alt")) == 2,
       "Zweiter Durchlauf veraendert nichts")

config.DB_FILE = neu_db
db._initialised = False
db.init()


print("\n=== 9. Muster ueber die Oberflaeche pflegen ===")
classics_key = db.add_station(name="Sunshine-Live Classics",
                              url="https://example.invalid/classics")
beginn = zeit.jetzt()
rid4 = "rec_classics"
db.create_recording(rid4, classics_key, "Sunshine-Live Classics",
                    "https://example.invalid/classics", "mp3",
                    started_at=zeit.text(beginn),
                    planned_end=zeit.text(zeit.plus_minuten(beginn, 29)),
                    work_dir=str(WORK), label="Test 6")
db.update_recording(rid4, state="completed",
                    ended_at=zeit.text(zeit.plus_minuten(beginn, 29)))
for position, roh in ((0, "sunshine live - Classics"),
                      (20, "Terry Bones - Dreaming (DJ Kalpa Mix)"),
                      (140, "DJ Quicksilver - Ameno [2000] (Club Mix)"),
                      (588, "Veracocha - Carte Blanche (Original Mix)"),
                      (1005, "Scooter - Jump That Rock (Whatever You Want)"),
                      (1347, "Tek Room - Fox 2000 (Extended Version)"),
                      (1500, "Dance Department - Armin Van Buuren")):
    interpret, titel = metadata.zerlege_titel(roh)
    db.add_track_mark(rid4, position, roh, interpret, titel)

seite = client.get("/recordings").get_data(as_text=True)
pruefe("6 Titel erkannt · 1 aussortiert" in seite,
       "Ohne Muster: Kennung raus, Sendungsname rutscht noch durch")
pruefe('class="aussortiert"' in seite and "Senderkennung" in seite,
       "Aussortiertes ist markiert und begruendet")
pruefe("Aussortiertes anzeigen" in seite, "Der Schalter ist da")

client.post(f"/stations/filters/{classics_key}",
            data={"muster": "  Dance Department \r\n\r\n"})
pruefe(db.get_station(classics_key)["title_filters"] == "Dance Department",
       "Muster wird bereinigt gespeichert",
       f"-> {db.get_station(classics_key)['title_filters']!r}")
seite = client.get("/recordings").get_data(as_text=True)
pruefe("5 Titel erkannt · 2 aussortiert" in seite,
       "Mit Muster faellt der Sendungsname weg - auch rueckwirkend")
pruefe("Muster des Senders: Dance Department" in seite,
       "Die Begruendung steht in der Liste")
pruefe(len(db.list_track_marks(rid4)) == 7,
       "In der Datenbank bleiben alle Rohmarken stehen")
pruefe("Sendungsnamen aussortieren (1)" in
       client.get("/stations").get_data(as_text=True),
       "Die Senderliste zeigt die Zahl der Muster")

client.post(f"/stations/filters/{classics_key}", data={"muster": "\n"})
pruefe(db.get_station(classics_key)["title_filters"] == "",
       "Leeres Feld entfernt die Muster")
pruefe("6 Titel erkannt" in client.get("/recordings").get_data(as_text=True),
       "Danach zaehlt der Sendungsname wieder mit")

antwort = client.post("/stations/filters/gibtesnicht", data={"muster": "x"})
pruefe(antwort.status_code in (302, 303),
       "Unbekannter Sender fuehrt nicht zum Absturz", f"-> {antwort.status_code}")

# Ohne einen einzigen Liedtitel - etwa bei Liveprogramm - gibt es einen Hinweis.
rid5 = "rec_live"
db.create_recording(rid5, classics_key, "Sunshine-Live Classics",
                    "https://example.invalid/classics", "mp3",
                    started_at=zeit.text(beginn),
                    planned_end=zeit.text(zeit.plus_minuten(beginn, 316)),
                    work_dir=str(WORK), label="Live")
db.update_recording(rid5, state="completed",
                    ended_at=zeit.text(zeit.plus_minuten(beginn, 316)))
db.add_track_mark(rid5, 0, "SUNSHINE LIVE - Simulcast", "SUNSHINE LIVE",
                  "Simulcast")
db.add_track_mark(rid5, 3600, "SUNSHINE LIVE - Simulcast", "SUNSHINE LIVE",
                  "Simulcast")
seite = client.get("/recordings").get_data(as_text=True)
pruefe("0 Titel erkannt · 2 aussortiert" in seite and "Kein Lied erkannt" in seite,
       "Liveprogramm ohne Titel bekommt einen Hinweis statt einer leeren Liste")


print("\n" + "=" * 62)
print(f"Bestanden: {len(bestanden)}   Fehlgeschlagen: {len(fehlgeschlagen)}")
for eintrag in fehlgeschlagen:
    print(f"  - {eintrag}")
print("=" * 62)
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if fehlgeschlagen else 0)
