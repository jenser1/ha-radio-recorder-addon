"""Zeitrechnung mit Zeitzone.

Alles, was mit Zeitpunkten gerechnet wird, laeuft ueber dieses Modul.

Der Grund ist die Umstellung zwischen Sommer- und Winterzeit. Ein
Zeitpunkt ohne Zeitzone weiss nicht, in welcher Zone er gilt - "zwei
Stunden spaeter" heisst dann "zwei Stunden auf dem Zifferblatt". In der
Umstellungsnacht ist das falsch: zwischen 01:30 und 03:30 liegen Ende
Maerz 60 Minuten und Ende Oktober 180. Tragen beide Zeitpunkte ihre Zone,
rechnet Python in absoluter Zeit und beruecksichtigt den Sprung von selbst.

Die Umstellungstermine kennt die Zeitzonendatenbank des Systems (Paket
``tzdata``, siehe Dockerfile), nicht Home Assistant. Von dort kommt nur
der Name der Zone.

Zeitstempel werden mit Zeitzonenversatz abgelegt, also als
``2026-10-25T02:30:00+02:00``. Aeltere Eintraege stehen ohne Versatz in
der Datenbank; ``lese`` deutet sie als Ortszeit, denn so wurden sie
geschrieben. Eine Schemaaenderung braucht es dafuer nicht.

Die Bibliothek sortiert nach diesem Text. Ueber den Versatz hinweg stimmt
das nicht ganz: in der doppelten Stunde Ende Oktober koennen zwei
Aufnahmen vertauscht erscheinen, ebenso eine alte ohne Versatz neben einer
neuen zur selben Uhrzeit. Das betrifft nur die Reihenfolge der Anzeige.
"""

from datetime import datetime, time, timedelta, timezone

from . import config

# Aufgeloeste Zone, gemerkt samt Name: aendert sich config.TIMEZONE (in
# Tests), wird neu aufgeloest, sonst bleibt es bei einer Meldung im Protokoll.
_zone = None
_zone_name = "\0"          # ein Wert, den config.TIMEZONE nie hat


def zone():
    """Die eingestellte Zeitzone, oder None, wenn keine brauchbar ist."""
    global _zone, _zone_name
    name = config.TIMEZONE
    if name == _zone_name:
        return _zone

    aufgeloest = None
    if not name:
        print("[zeit] Keine Zeitzone gesetzt - verwende die des Systems. "
              "Zeitplaene koennen dadurch verschoben sein.", flush=True)
    else:
        try:
            from zoneinfo import ZoneInfo
            aufgeloest = ZoneInfo(name)
        except Exception as err:
            print(f"[zeit] Zeitzone {name!r} unbekannt ({err}) - "
                  f"verwende die des Systems.", flush=True)

    _zone_name, _zone = name, aufgeloest
    return _zone


def jetzt():
    """Der aktuelle Zeitpunkt, immer mit Zeitzone."""
    eigene = zone()
    if eigene is None:
        # Ohne eingestellte Zone die des Systems anhaengen - Hauptsache, es
        # wird nicht mit zonenlosen Zeitpunkten weitergerechnet.
        return datetime.now().astimezone()
    return datetime.now(eigene)


def ortszeit(moment):
    """Haengt die Zeitzone an bzw. rechnet in sie um."""
    eigene = zone()
    if moment.tzinfo is not None:
        return moment.astimezone(eigene) if eigene else moment

    if eigene is None:
        return moment.astimezone()
    # Nach dem Anhaengen noch einmal umrechnen: Ende Maerz gibt es die
    # Stunde 02:00-02:59 nicht. Ein "02:30" bezeichnet dann zwar einen
    # eindeutigen Zeitpunkt, zeigen wuerde die Uhr dort aber 03:30 - und
    # genau das soll auch in der Anzeige und in der Datenbank stehen.
    angehaengt = moment.replace(tzinfo=eigene)
    # Der Weg ueber UTC ist noetig: ``astimezone`` in dieselbe Zone liefert
    # den Zeitpunkt unveraendert zurueck und wuerde nichts richtigstellen.
    return angehaengt.astimezone(timezone.utc).astimezone(eigene)


def lese(wert):
    """Zeitstempel aus der Datenbank einlesen. None, wenn unbrauchbar.

    Zeitpunkte ohne Versatz stammen aus einer aelteren Fassung und waren
    Ortszeit - sie werden auch so gedeutet.
    """
    if isinstance(wert, datetime):
        return ortszeit(wert)
    try:
        return ortszeit(datetime.fromisoformat(wert))
    except (TypeError, ValueError):
        return None


def text(moment):
    """Zeitstempel fuer die Datenbank, auf Sekunden genau."""
    return ortszeit(moment).isoformat(timespec="seconds")


def von_zeitstempel(sekunden):
    """Unix-Zeit (etwa aus ``stat``) als Zeitpunkt mit Zone."""
    eigene = zone()
    if eigene is None:
        return datetime.fromtimestamp(sekunden).astimezone()
    return datetime.fromtimestamp(sekunden, eigene)


def absolut(moment):
    """Derselbe Zeitpunkt in UTC. Nur so darf gerechnet werden.

    Python vergleicht und subtrahiert zwei Zeitpunkte, die *dasselbe*
    ``tzinfo``-Objekt tragen, ohne Blick auf den Versatz - also wieder wie
    Werte auf dem Zifferblatt. Und ``ZoneInfo`` gibt fuer eine Zone immer
    dasselbe Objekt heraus. Ohne diesen Umweg waere in der Umstellungsnacht
    alles beim alten: 01:30 MESZ bis 03:30 MEZ ergaebe zwei Stunden statt
    drei, und 02:30 MESZ und 02:30 MEZ gaelten als derselbe Zeitpunkt.
    """
    return ortszeit(moment).astimezone(timezone.utc)


def sekunden_zwischen(von, bis):
    """Abstand in Sekunden, auf absoluter Zeit gerechnet."""
    return (absolut(bis) - absolut(von)).total_seconds()


def minuten_zwischen(von, bis):
    """Abstand in ganzen Minuten, auf absoluter Zeit gerechnet."""
    return round(sekunden_zwischen(von, bis) / 60)


def sekunden_bis(ziel):
    """Wie viele Sekunden noch bis ``ziel``. Negativ, wenn schon vorbei."""
    return sekunden_zwischen(jetzt(), ziel)


def plus_sekunden(moment, sekunden):
    """``sekunden`` wirkliche Sekunden spaeter, als Ortszeit."""
    return ortszeit(absolut(moment) + timedelta(seconds=sekunden))


def plus_minuten(moment, minuten):
    """``minuten`` wirkliche Minuten spaeter, als Ortszeit.

    Ende Oktober liegt der Zeitpunkt zwei Stunden nach 01:30 MESZ bei
    02:30 MEZ, nicht bei 03:30.
    """
    return plus_sekunden(moment, minuten * 60)


def wandzeitpunkt(ab, stunde, minute):
    """Der naechste Zeitpunkt nach ``ab``, an dem die Uhr ``stunde:minute`` zeigt.

    Damit wird aus einer Endzeit wie "03:30" ein wirklicher Zeitpunkt, und
    die Dauer dahin ergibt sich von selbst - in der Umstellungsnacht eben
    60 oder 180 Minuten statt der 120 vom Zifferblatt.

    Zwei Sonderfaelle hat diese Nacht:

    * Ende Maerz fehlt die Stunde 02:00-02:59. Eine Endzeit darin wandert
      um eine Stunde nach hinten - genauso, wie APScheduler eine Startzeit
      in dieser Luecke behandelt.
    * Ende Oktober gibt es 02:00-02:59 zweimal. Gemeint ist das erste Mal,
      noch in der Sommerzeit.
    """
    ab = ortszeit(ab)
    for tage in (0, 1, 2):
        kandidat = ortszeit(datetime.combine(ab.date() + timedelta(days=tage),
                                             time(stunde, minute)))
        if sekunden_zwischen(ab, kandidat) > 0:
            return kandidat
    # Unerreichbar: schon der Folgetag liegt immer hinter ``ab``.
    raise ValueError(f"Kein Zeitpunkt {stunde:02d}:{minute:02d} nach {ab}")
