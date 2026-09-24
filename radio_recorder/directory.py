"""Sendersuche ueber radio-browser.info.

Ein offenes Verzeichnis mit rund 50.000 Internetradios, ohne Anmeldung und
ohne Schluessel. Gesucht wird nur auf ausdruecklichen Wunsch; uebernommen
wird ein Treffer erst, wenn er in der Oberflaeche ausgewaehlt wurde.

Die Antworten sind fremde Daten: sie werden ausschliesslich als Vorschlag
fuer Name und Stream-Adresse verwendet, nie als Anweisung.
"""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

# Sammeladresse des Verzeichnisses. Verteilt selbst auf die Spiegelserver.
BASIS = "https://all.api.radio-browser.info/json/stations/search"

# Das Verzeichnis bittet ausdruecklich um eine aussagekraeftige Kennung.
USER_AGENT = f"HomeAssistantRadioRecorder/{__version__}"

TIMEOUT = 12
MAX_TREFFER = 25


class DirectoryError(Exception):
    """Suche nicht moeglich - Netz, Zeitueberschreitung oder Fehlermeldung."""


def search(begriff, limit=MAX_TREFFER):
    """Sucht Sender nach Namen und liefert eine aufgeraeumte Trefferliste."""
    begriff = (begriff or "").strip()
    if len(begriff) < 2:
        raise DirectoryError("Bitte mindestens zwei Zeichen eingeben.")

    anfrage = BASIS + "?" + urllib.parse.urlencode({
        "name": begriff,
        "limit": max(1, min(int(limit), MAX_TREFFER)),
        "hidebroken": "true",
        "order": "clickcount",
        "reverse": "true",
    })

    try:
        antwort = _hole(anfrage)
    except urllib.error.HTTPError as err:
        raise DirectoryError(
            f"Das Senderverzeichnis antwortete mit {err.code}.") from None
    except (urllib.error.URLError, socket.timeout, TimeoutError) as err:
        raise DirectoryError(
            f"Das Senderverzeichnis ist nicht erreichbar ({err}). "
            f"Hat das Add-on Zugang zum Internet?") from None
    except json.JSONDecodeError:
        raise DirectoryError("Die Antwort des Verzeichnisses war unlesbar.") from None

    treffer = []
    for eintrag in antwort if isinstance(antwort, list) else []:
        aufbereitet = _aufbereiten(eintrag)
        if aufbereitet:
            treffer.append(aufbereitet)
    return treffer


def _hole(adresse):
    anfrage = urllib.request.Request(
        adresse, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(anfrage, timeout=TIMEOUT) as antwort:
        roh = antwort.read(2_000_000)
    return json.loads(roh.decode("utf-8", errors="replace"))


def _aufbereiten(eintrag):
    """Uebernimmt nur die Felder, die wirklich gebraucht werden."""
    if not isinstance(eintrag, dict):
        return None

    adresse = (eintrag.get("url_resolved") or eintrag.get("url") or "").strip()
    name = (eintrag.get("name") or "").strip()
    if not name or not adresse.lower().startswith(("http://", "https://")):
        return None

    try:
        bitrate = int(eintrag.get("bitrate") or 0)
    except (TypeError, ValueError):
        bitrate = 0

    return {
        "name": name[:120],
        "url": adresse,
        "codec": (eintrag.get("codec") or "").strip().lower() or None,
        "bitrate_kbps": bitrate or None,
        "country": (eintrag.get("country") or "").strip()[:60] or None,
        "homepage": (eintrag.get("homepage") or "").strip()[:200] or None,
    }
