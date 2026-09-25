"""Titelmeldungen eines Senders auswerten (ICY-Metadaten).

Internetradios betten in den Tonstrom kurze Textbloecke ein. Bei jedem
Liedwechsel steht darin ``StreamTitle='Interpret - Titel'``. Genau daraus
entsteht spaeter die Zerlegung einer Aufnahme in Einzeltitel.

ffmpeg liest diese Bloecke von sich aus mit und schreibt sie in seine
Fehlerausgabe - dieselbe, die beim Aufnehmen ohnehin gelesen wird. Eine
zweite Verbindung zum Sender ist dadurch nicht noetig.

Die genaue Schreibweise dieser Zeilen haengt von der ffmpeg-Fassung ab,
darum erkennt der Parser mehrere Formen und ``pruefe_sender`` haelt die
Rohzeilen fest.
"""

import re
import subprocess
import threading
import time
from collections import deque

from . import config

# Bekannte Schreibweisen, in denen ffmpeg den Titel meldet:
#   Metadata update for StreamTitle: Interpret - Titel
#   StreamTitle     : Interpret - Titel
#   StreamTitle='Interpret - Titel';
TITEL_MUSTER = re.compile(
    r"StreamTitle\s*(?:=\s*['\"]|:\s*)(?P<titel>[^'\"\r\n]*)")

# Zeilen, die zwar StreamTitle enthalten, aber keinen Inhalt tragen.
LEER = {"", "-", "unknown", "n/a"}

# So lange wird beim Pruefen mitgehoert.
PRUEF_DAUER = 45


def titel_aus_zeile(zeile):
    """Zieht den Titel aus einer ffmpeg-Zeile, sonst None."""
    treffer = TITEL_MUSTER.search(zeile or "")
    if not treffer:
        return None
    titel = treffer.group("titel").strip().rstrip(";").strip()
    if titel.lower() in LEER:
        return None
    return titel


def zerlege_titel(titel):
    """Trennt 'Interpret - Titel' auf. Ohne Trenner gilt alles als Titel."""
    if not titel:
        return None, ""
    for trenner in (" - ", " – ", " — "):
        if trenner in titel:
            interpret, rest = titel.split(trenner, 1)
            interpret, rest = interpret.strip(), rest.strip()
            if interpret and rest:
                return interpret, rest
    return None, titel.strip()


def pruefe_sender(url, dauer=PRUEF_DAUER):
    """Hoert kurz in den Strom und meldet, was an Titeln ankommt.

    Liefert ein Woerterbuch mit ``titel`` (Reihenfolge des Auftretens),
    ``rohzeilen`` (zum Nachsehen, welche Schreibweise der Sender liefert)
    und ``fehler``.
    """
    ergebnis = {"titel": [], "rohzeilen": [], "dauer": dauer, "fehler": None}

    befehl = [
        *config.FFMPEG,
        "-hide_banner",
        # ausfuehrlich, damit die Titelmeldungen ueberhaupt auftauchen
        "-loglevel", "verbose",
        "-nostats",
        "-nostdin",
        "-icy", "1",
        "-i", url,
        "-vn",
        "-t", str(int(dauer)),
        "-f", "null",
        "-",
    ]

    try:
        proc = subprocess.Popen(
            befehl, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, errors="replace")
    except (OSError, ValueError) as err:
        ergebnis["fehler"] = f"ffmpeg liess sich nicht starten ({err})."
        return ergebnis

    zeilen = deque(maxlen=400)
    leser = threading.Thread(target=_mitlesen, args=(proc, zeilen), daemon=True)
    leser.start()

    # Notbremse, falls der Strom haengt und -t nie greift.
    grenze = time.monotonic() + dauer + 20
    while proc.poll() is None and time.monotonic() < grenze:
        time.sleep(0.3)
    if proc.poll() is None:
        proc.kill()
        ergebnis["fehler"] = "Der Sender hat nicht rechtzeitig geantwortet."
    leser.join(timeout=5)
    rueckgabe = proc.returncode

    gesehen = []
    for zeile in zeilen:
        titel = titel_aus_zeile(zeile)
        if titel and (not gesehen or gesehen[-1] != titel):
            gesehen.append(titel)
            ergebnis["rohzeilen"].append(zeile.strip()[:200])

    ergebnis["titel"] = gesehen

    # Auch ins Protokoll, damit sich hinterher nachvollziehen laesst, was
    # der Sender tatsaechlich geliefert hat - in der Oberflaeche ist das
    # nur eine kurzlebige Meldung.
    if gesehen:
        print(f"[titel] {url}: {len(gesehen)} Titel in {dauer}s", flush=True)
        for zeile in ergebnis["rohzeilen"][:10]:
            print(f"[titel]   {zeile}", flush=True)
    else:
        print(f"[titel] {url}: kein Titel in {dauer}s "
              f"(Rueckgabe {proc.returncode})", flush=True)
        for zeile in list(zeilen)[-6:]:
            print(f"[titel]   {zeile.strip()[:200]}", flush=True)

    if not gesehen and not ergebnis["fehler"]:
        # Massgeblich ist der Rueckgabewert, nicht der Wortlaut: eine Meldung
        # wie "Server returned 404 Not Found" enthaelt weder "error" noch
        # "failed" und wuerde sonst als "Sender meldet halt nichts" durchgehen.
        if rueckgabe not in (0, 255):
            ergebnis["fehler"] = (_letzte_aussagekraeftige_zeile(zeilen)
                                  or f"ffmpeg endete mit Code {rueckgabe}")

    return ergebnis


def _letzte_aussagekraeftige_zeile(zeilen):
    for zeile in reversed(zeilen):
        gestutzt = zeile.strip()
        if gestutzt:
            return gestutzt[:200]
    return ""


def _mitlesen(proc, zeilen):
    try:
        for zeile in proc.stderr:
            zeilen.append(zeile)
    except Exception:
        pass
