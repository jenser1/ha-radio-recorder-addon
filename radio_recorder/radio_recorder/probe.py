"""Stream mit ffprobe untersuchen.

Wozu: mit ``-c:a copy`` wird der Ton unveraendert durchgereicht. Steckt in
einem Stream AAC, muss die Datei auch ein AAC-Behaeltnis sein - eine
".mp3" mit AAC-Inhalt waere kaputt. Bisher stand die Endung fest im Code;
jetzt wird sie beim Anlegen eines Senders ermittelt.
"""

import json
import subprocess

from . import config

# Welcher Codec in welches Behaeltnis gehoert und wie das Segmentformat heisst.
CODEC_MAP = {
    "mp3":       ("mp3",  "mp3"),
    "aac":       ("aac",  "adts"),
    "aac_latm":  ("aac",  "adts"),
    "vorbis":    ("ogg",  "ogg"),
    "opus":      ("opus", "ogg"),
    "flac":      ("flac", "flac"),
}

PROBE_TIMEOUT = 20


def extension_for(codec):
    """Passende Dateiendung zu einem Codec, mp3 als Rueckfallebene."""
    return CODEC_MAP.get((codec or "").lower(), ("mp3", "mp3"))[0]


def segment_format_for(ext):
    for behaeltnis, segmentformat in CODEC_MAP.values():
        if behaeltnis == ext:
            return segmentformat
    return ext


def probe_stream(url):
    """Ermittelt Codec, Bitrate und Sendernamen eines Streams.

    Liefert immer ein Wörterbuch. Konnte nichts ermittelt werden, steht in
    ``fehler`` der Grund und die uebrigen Werte sind Vorgaben - der Sender
    laesst sich dann trotzdem anlegen.

    Das Ergebnis geht auch ins Protokoll: in der Oberflaeche ist es nur eine
    kurzlebige Meldung, zum Nachsehen braucht es eine dauerhafte Spur.
    """
    befund = _probe_stream(url)
    if befund["fehler"]:
        print(f"[probe] {url}: {befund['fehler']}", flush=True)
    else:
        print(f"[probe] {url}: {befund['codec']}, "
              f"{befund['bitrate_kbps']} kbit/s -> .{befund['ext']}"
              + (f", Name {befund['name']!r}" if befund["name"] else ""),
              flush=True)
    return befund


def _probe_stream(url):
    ergebnis = {
        "codec": None,
        "ext": "mp3",
        "bitrate_kbps": config.DEFAULT_BITRATE_KBPS,
        "name": None,
        "fehler": None,
    }

    befehl = [
        *_ffprobe_befehl(),
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,bit_rate:"
                         "format=bit_rate:format_tags=icy-name,StreamTitle",
        "-of", "json",
        "-rw_timeout", str(PROBE_TIMEOUT * 1_000_000),
        url,
    ]

    try:
        lauf = subprocess.run(befehl, capture_output=True, text=True,
                              errors="replace", timeout=PROBE_TIMEOUT)
    except FileNotFoundError:
        ergebnis["fehler"] = "ffprobe wurde nicht gefunden."
        return ergebnis
    except subprocess.TimeoutExpired:
        ergebnis["fehler"] = (f"Der Stream hat innerhalb von "
                              f"{PROBE_TIMEOUT} Sekunden nicht geantwortet.")
        return ergebnis
    except OSError as err:
        ergebnis["fehler"] = f"ffprobe liess sich nicht starten ({err})."
        return ergebnis

    if lauf.returncode != 0:
        ergebnis["fehler"] = (lauf.stderr or "").strip().splitlines()[-1:] or [
            f"ffprobe endete mit Code {lauf.returncode}"]
        ergebnis["fehler"] = ergebnis["fehler"][0][:300]
        return ergebnis

    try:
        daten = json.loads(lauf.stdout or "{}")
    except json.JSONDecodeError:
        ergebnis["fehler"] = "Die Antwort von ffprobe war unlesbar."
        return ergebnis

    spuren = daten.get("streams") or []
    if not spuren:
        ergebnis["fehler"] = "Der Stream enthaelt keine Tonspur."
        return ergebnis

    spur = spuren[0]
    ergebnis["codec"] = spur.get("codec_name")
    ergebnis["ext"] = extension_for(ergebnis["codec"])

    bitrate = _erste_zahl(spur.get("bit_rate"),
                          (daten.get("format") or {}).get("bit_rate"))
    if bitrate:
        ergebnis["bitrate_kbps"] = max(8, round(bitrate / 1000))

    marken = (daten.get("format") or {}).get("tags") or {}
    for schluessel in ("icy-name", "ICY-NAME", "StreamTitle"):
        wert = (marken.get(schluessel) or "").strip()
        if wert:
            ergebnis["name"] = wert
            break

    return ergebnis


def probe_file(pfad):
    """Liest Spieldauer und Codec einer fertigen Datei.

    Anders als beim Stream geht das schnell, weil ffprobe nur den Kopf der
    Datei liest. Bei Unlesbarkeit steht in ``fehler`` der Grund.
    """
    ergebnis = {"duration_seconds": None, "codec": None,
                "bitrate_kbps": None, "fehler": None}

    befehl = [
        *_ffprobe_befehl(),
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name:format=duration,bit_rate",
        "-of", "json",
        str(pfad),
    ]

    try:
        lauf = subprocess.run(befehl, capture_output=True, text=True,
                              errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as err:
        ergebnis["fehler"] = f"ffprobe nicht nutzbar ({err})"
        return ergebnis

    if lauf.returncode != 0:
        ergebnis["fehler"] = (lauf.stderr or "").strip()[-200:] or "unlesbar"
        return ergebnis

    try:
        daten = json.loads(lauf.stdout or "{}")
    except json.JSONDecodeError:
        ergebnis["fehler"] = "Antwort von ffprobe unlesbar"
        return ergebnis

    format_teil = daten.get("format") or {}
    try:
        dauer = float(format_teil.get("duration"))
        ergebnis["duration_seconds"] = dauer if dauer > 0 else None
    except (TypeError, ValueError):
        pass

    spuren = daten.get("streams") or []
    if spuren:
        ergebnis["codec"] = spuren[0].get("codec_name")

    bitrate = _erste_zahl(format_teil.get("bit_rate"))
    if bitrate:
        ergebnis["bitrate_kbps"] = max(8, round(bitrate / 1000))

    return ergebnis


def _ffprobe_befehl():
    """ffprobe liegt neben ffmpeg - auch wenn der Aufruf ersetzt wurde."""
    aufruf = list(config.FFMPEG)
    aufruf[-1] = aufruf[-1].replace("ffmpeg", "ffprobe")
    return aufruf


def _erste_zahl(*werte):
    for wert in werte:
        try:
            zahl = int(wert)
        except (TypeError, ValueError):
            continue
        if zahl > 0:
            return zahl
    return None
