"""Entscheidet, welche Titelmeldung wirklich ein Lied ist.

Sender melden ueber ICY nicht nur Liedwechsel, sondern auch ihre eigene
Kennung, Sendungsnamen, Werbung und bei moderiertem Programm minutenlang
dasselbe. Was davon ein Lied ist, laesst sich nur am Text und an den
Abstaenden ablesen - mehr liefert der Strom nicht.

Aussortiert wird erst beim Anzeigen. In ``track_marks`` bleibt jede
Meldung roh stehen: so wirken bessere Regeln auch auf laengst
abgeschlossene Aufnahmen zurueck, und eine Fehlentscheidung kostet nichts
ausser einem Haken in der Oberflaeche.
"""

import re
import unicodedata

# Urteile. Alles ausser LIED wird in der Bibliothek ausgegraut.
LIED = "lied"
KENNUNG = "kennung"
SENDUNG = "sendung"
WERBUNG = "werbung"
DUBLETTE = "dublette"
KURZ = "kurz"

URTEIL_TEXT = {
    LIED: "Lied",
    KENNUNG: "Senderkennung",
    SENDUNG: "Sendung",
    WERBUNG: "Werbung",
    DUBLETTE: "Wiederholung",
    KURZ: "zu kurz",
}

# Kuerzer als das gilt nicht als Lied. Belegt an einer Classics-Aufnahme:
# die Senderkennung stand 20 Sekunden, die Stuecke zwei bis sieben Minuten.
MINDESTDAUER = 60.0

# Woerter, die zur Senderkennung gehoeren, aber nicht im eingetragenen
# Namen stehen muessen - "SUNSHINE LIVE - Simulcast" ist der Sender, nicht
# ein Stueck von "Sunshine Live". Sie zaehlen nur mit: eine Meldung gilt
# erst dann als Kennung, wenn ausserdem jedes uebrige Wort zum Sendernamen
# gehoert. Ein Stueck der Band "Live" bleibt dadurch unangetastet.
NEBENWORTE = frozenset({
    "simulcast", "livestream", "stream", "webradio", "radio", "fm", "ukw",
    "hd", "online", "playlist", "kanal", "channel", "sender", "the", "de",
})

WERBEWORTE = frozenset({
    "werbung", "werbeblock", "reklame", "advertisement", "advert", "ads",
    "commercial", "jingle", "spot", "trailer",
})


def beurteile(marken, sendername=None, muster=None, gesamtdauer=None,
              mindestdauer=MINDESTDAUER):
    """Beurteilt jede Marke und liefert Kopien mit ``urteil`` und ``grund``.

    ``marken`` ist die Rohliste aus ``db.list_track_marks`` (nach Position
    sortiert). ``gesamtdauer`` ist die Spieldauer der Aufnahme in Sekunden
    und wird nur fuer die letzte Marke gebraucht; ohne sie bleibt die
    letzte von der Dauerregel verschont, statt auf Verdacht zu fliegen.
    """
    sender_woerter = set(_woerter(sendername)) | NEBENWORTE
    muster_liste = [m for m in (muster or []) if m and m.strip()]

    ergebnis = []
    voriger = None
    for i, marke in enumerate(marken):
        roh = (marke.get("title") or "").strip()
        abstand = _abstand(marken, i, gesamtdauer)
        urteil, grund = _urteil(roh, voriger, sender_woerter, muster_liste,
                                abstand, mindestdauer)
        ergebnis.append(dict(marke, urteil=urteil, lied=(urteil == LIED),
                             grund=grund, abstand_s=abstand))
        voriger = roh
    return ergebnis


def lieder(beurteilte):
    return [m for m in beurteilte if m["lied"]]


def muster_aus_text(text):
    """Eine Zeile je Muster, Leerzeilen fallen weg."""
    return [zeile.strip() for zeile in (text or "").splitlines() if zeile.strip()]


def text_aus_muster(muster):
    return "\n".join(muster or [])


def _urteil(roh, voriger, sender_woerter, muster, abstand, mindestdauer):
    if not roh:
        return KENNUNG, "Leere Meldung"

    # Zuerst die Wiederholung: bei Liveprogramm steht stundenlang dasselbe
    # da, und das sind keine zwei Lieder.
    if voriger is not None and _woerter(roh) == _woerter(voriger):
        return DUBLETTE, "Wiederholung der vorigen Meldung"

    woerter = _woerter(roh)
    if woerter and all(w in sender_woerter for w in woerter):
        return KENNUNG, "Nennt nur den Sender"

    if woerter and any(w in WERBEWORTE for w in woerter) and all(
            w in WERBEWORTE or w in sender_woerter for w in woerter):
        return WERBUNG, "Werbung oder Jingle"

    treffer = _muster_treffer(roh, muster)
    if treffer:
        return SENDUNG, f"Muster des Senders: {treffer}"

    # Zuletzt die Dauer. Sie steht hinten, damit in der Begruendung lieber
    # der inhaltliche Grund steht, wenn es einen gibt.
    if abstand is not None and abstand < mindestdauer:
        return KURZ, f"nur {int(abstand)} Sekunden bis zur naechsten Meldung"

    return LIED, ""


def _abstand(marken, i, gesamtdauer):
    """Sekunden bis zur naechsten Meldung, bei der letzten bis zum Ende."""
    hier = _zahl(marken[i].get("position_s"))
    if hier is None:
        return None
    if i + 1 < len(marken):
        naechste = _zahl(marken[i + 1].get("position_s"))
        return None if naechste is None else max(0.0, naechste - hier)
    if gesamtdauer is None:
        return None
    return max(0.0, float(gesamtdauer) - hier)


def _zahl(wert):
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _muster_treffer(roh, muster):
    unten = roh.casefold()
    for eintrag in muster:
        if eintrag.strip().casefold() in unten:
            return eintrag.strip()
    return None


def _woerter(text):
    """Text in vergleichbare Woerter zerlegen.

    Gross- und Kleinschreibung, Umlaute, Binde- und Satzzeichen
    unterscheiden sich von Meldung zu Meldung; "Sunshine-Live" und
    "SUNSHINE LIVE" sind derselbe Sender.
    """
    if not text:
        return []
    gefaltet = unicodedata.normalize("NFKD", text.casefold())
    ohne_zeichen = "".join(c for c in gefaltet if not unicodedata.combining(c))
    return [w for w in re.split(r"[^0-9a-z]+", ohne_zeichen) if w]
