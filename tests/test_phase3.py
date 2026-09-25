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


print("\n" + "=" * 62)
print(f"Bestanden: {len(bestanden)}   Fehlgeschlagen: {len(fehlgeschlagen)}")
for eintrag in fehlgeschlagen:
    print(f"  - {eintrag}")
print("=" * 62)
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if fehlgeschlagen else 0)
