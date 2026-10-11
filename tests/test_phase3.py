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

from radio_recorder import config, db, metadata, web          # noqa: E402

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
pruefe("gemeldete Titel" in seite, "Titelliste erscheint in der Bibliothek")
pruefe("Erster" in seite, "Die Titel stehen darin")
pruefe("noch nicht gefiltert" in seite,
       "Der Hinweis auf die fehlende Filterung steht dabei")

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


print("\n" + "=" * 62)
print(f"Bestanden: {len(bestanden)}   Fehlgeschlagen: {len(fehlgeschlagen)}")
for eintrag in fehlgeschlagen:
    print(f"  - {eintrag}")
print("=" * 62)
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if fehlgeschlagen else 0)
