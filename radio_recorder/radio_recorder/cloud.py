"""Kopie fertiger Aufnahmen in die Cloud, ueber rclone.

Der Zielordner bleibt das eigentliche Ziel - die Cloud bekommt nur
zusaetzlich eine Kopie, und nur auf Wunsch. Daraus folgt:

* Ein Upload laeuft nie im Aufnahme-Thread. Vier Stunden Aufnahme sind
  rund 350 MB; bei schmalem Upstream dauert das eine Dreiviertelstunde,
  und so lange darf der naechste Zeitplan nicht warten.
* Der Zustand steht in der Datenbank. Ein Upload, den ein Neustart
  unterbricht, wird danach wieder aufgenommen.
* Schlaegt ein Upload fehl, bleibt die Aufnahme im Zielordner unberuehrt.
  Die Bibliothek zeigt den Fehler und bietet einen neuen Versuch an.

Fuer WebDAV und S3 erzeugt das Add-on die rclone-Konfiguration selbst aus
den Optionen. Anbieter mit Anmeldung im Browser (Google Drive, Dropbox,
OneDrive) brauchen eine eigene rclone.conf - diese Anmeldung laesst sich
innerhalb des Add-ons nicht durchfuehren.
"""

import configparser
import os
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import config, db, zeit
from .recorder import format_size

TYPEN = ("webdav", "s3", "rclone")

# Kurz, weil sie als Abzeichen in der Statusspalte stehen und dort nicht
# umbrechen - lange Texte machten die Bibliothek auf dem Handy zu breit.
ZUSTAND_TEXT = {
    "queued": "wartet",
    "uploading": "laedt hoch",
    "done": "in der Cloud",
    "failed": "Fehler",
}

# Name des Remotes in der selbst erzeugten Konfiguration. Ungewoehnlich
# genug, um mit keinem Remote einer eigenen rclone.conf zusammenzustossen.
_EIGENER_REMOTE = "radio_recorder_cloud"

# rclone wird mit --retries 1 aufgerufen; wiederholt wird hier. So steht
# jeder Versuch im Protokoll, und ein Neustart dazwischen geht nicht verloren.
VERSUCHE = 3
PAUSE_SEKUNDEN = 60

# Wann rclone als haengend gilt: langsamer als diese Rate, mindestens zehn
# Minuten, hoechstens zwoelf Stunden.
_MINDESTRATE = 50 * 1024
_MINDESTZEIT = 10 * 60
_HOECHSTZEIT = 12 * 3600

# Ohne Warteschlange wird trotzdem regelmaessig nachgesehen - falls ein
# Wecksignal verloren geht, bleibt dadurch nichts liegen.
_NACHSEHEN_SEKUNDEN = 300

_wecker = threading.Event()
_halt = threading.Event()
_lock = threading.Lock()
_thread = None
_verschleiert = {}


class CloudFehler(Exception):
    """Ein Upload ist gescheitert; die Meldung ist fuer Menschen gedacht."""


# --- Einrichtung ---------------------------------------------------------

def eingeschaltet():
    return config.CLOUD_TYPE not in ("", "aus")


def fehlende_angaben():
    """Was in den Add-on-Optionen noch fehlt. Leer, wenn alles da ist."""
    art = config.CLOUD_TYPE
    if not eingeschaltet():
        return []
    if art not in TYPEN:
        return [f"cloud_type {art!r} ist unbekannt (erlaubt: "
                f"{', '.join(TYPEN)})"]

    fehlt = []
    if art == "webdav":
        for name, wert in (("cloud_url", config.CLOUD_URL),
                           ("cloud_user", config.CLOUD_USER),
                           ("cloud_password", config.CLOUD_PASSWORD)):
            if not wert:
                fehlt.append(name)
    elif art == "s3":
        for name, wert in (("cloud_url (Endpunkt)", config.CLOUD_URL),
                           ("cloud_user (Zugriffsschluessel)", config.CLOUD_USER),
                           ("cloud_password (geheimer Schluessel)",
                            config.CLOUD_PASSWORD),
                           ("cloud_path (Bucket)", config.CLOUD_PATH)):
            if not wert:
                fehlt.append(name)
    elif art == "rclone":
        if not config.CLOUD_REMOTE:
            fehlt.append("cloud_remote")
        if not Path(config.CLOUD_CONFIG).is_file():
            fehlt.append(f"rclone.conf unter {config.CLOUD_CONFIG}")
    return fehlt


def bereit():
    return eingeschaltet() and not fehlende_angaben()


def ziel_beschreibung():
    """Wohin hochgeladen wird - ohne Zugangsdaten, fuer Anzeige und Protokoll."""
    art = config.CLOUD_TYPE
    pfad = config.CLOUD_PATH
    if art == "webdav":
        return f"WebDAV {_ohne_zugang(config.CLOUD_URL)}" + (f" · {pfad}" if pfad else "")
    if art == "s3":
        return f"S3 {_ohne_zugang(config.CLOUD_URL)} · {pfad}"
    if art == "rclone":
        return f"{config.CLOUD_REMOTE}:{pfad}"
    return ""


def uebersicht():
    """Stand der Einrichtung fuer die Oberflaeche."""
    return {
        "eingeschaltet": eingeschaltet(),
        "bereit": bereit(),
        "fehlt": fehlende_angaben(),
        "ziel": ziel_beschreibung(),
        "auto": config.CLOUD_AUTO,
        "wartend": len(db.cloud_warteschlange()) if eingeschaltet() else 0,
    }


# --- Warteschlange -------------------------------------------------------

def einreihen(recording_id):
    """Stellt eine Aufnahme zum Hochladen an. Wirft ValueError mit Begruendung."""
    eintrag = db.get_recording(recording_id)
    if eintrag is None:
        raise ValueError("Diese Aufnahme gibt es nicht mehr.")
    if not eingeschaltet():
        raise ValueError("Die Cloud ist nicht eingerichtet. Das geschieht in "
                         "den Add-on-Optionen unter cloud_type.")
    fehlt = fehlende_angaben()
    if fehlt:
        raise ValueError("In den Add-on-Optionen fehlt fuer die Cloud noch: "
                         + ", ".join(fehlt))
    if eintrag["state"] == "running":
        raise ValueError("Diese Aufnahme laeuft noch.")
    datei = eintrag.get("output_file")
    if not datei or not Path(datei).is_file():
        raise ValueError("Die Datei der Aufnahme ist nicht mehr vorhanden.")
    if eintrag.get("cloud_state") in ("queued", "uploading"):
        raise ValueError("Diese Aufnahme steht bereits zum Hochladen an.")

    db.update_recording(recording_id, cloud_state="queued", cloud_error=None,
                        cloud_target=ziel_beschreibung(),
                        cloud_at=zeit.text(zeit.jetzt()))
    _wecker.set()


def soll_automatisch(eintrag):
    """Ob eine fertige Aufnahme von selbst hochgeladen werden soll."""
    if config.CLOUD_AUTO:
        return True
    job_id = eintrag.get("job_id")
    if not job_id:
        return False
    job = db.get_job(job_id)
    return bool(job and job["cloud_auto"])


def nach_aufnahme(recording_id):
    """Wird vom Recorder gerufen, sobald eine Aufnahme fertig ist."""
    eintrag = db.get_recording(recording_id)
    # Nur vollstaendige Aufnahmen. Wer von Hand stoppt, entscheidet selbst,
    # ob das Teilstueck in die Cloud soll.
    if not eintrag or eintrag["state"] != "completed":
        return False
    if not soll_automatisch(eintrag):
        return False
    try:
        einreihen(recording_id)
    except ValueError as err:
        print(f"[cloud {recording_id}] Nicht hochgeladen: {err}", flush=True)
        return False
    print(f"[cloud {recording_id}] Zum Hochladen vorgemerkt", flush=True)
    return True


# --- Hintergrund-Thread --------------------------------------------------

def start():
    """Startet die Abarbeitung. Holt beim Beenden unterbrochene Uploads nach."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _halt.clear()

        zurueck = db.cloud_unterbrochene_freigeben()
        if zurueck:
            print(f"[cloud] {zurueck} unterbrochene(r) Upload(s) wieder "
                  f"eingereiht", flush=True)
        if bereit():
            print(f"[cloud] Ziel: {ziel_beschreibung()}"
                  f"{' - jede Aufnahme automatisch' if config.CLOUD_AUTO else ''}",
                  flush=True)
        elif eingeschaltet():
            print(f"[cloud] WARNUNG: Cloud eingeschaltet, es fehlt aber: "
                  f"{', '.join(fehlende_angaben())}", flush=True)

        _thread = threading.Thread(target=_schleife, name="cloud-upload",
                                   daemon=True)
        _thread.start()
        _wecker.set()


def shutdown():
    """Beendet die Abarbeitung. Ein laufender Upload wird beim Neustart wiederholt."""
    _halt.set()
    _wecker.set()


def _schleife():
    while not _halt.is_set():
        try:
            if verarbeite_einen():
                continue
        except Exception as err:
            # Etwa eine gesperrte Datenbank, waehrend schon der Fehlschlag
            # vermerkt werden sollte. Stirbt der Thread, laedt bis zum
            # naechsten Neustart nichts mehr hoch - also weiter nach der Pause.
            print(f"[cloud] Unerwarteter Fehler: {err}", flush=True)
        _wecker.wait(timeout=_NACHSEHEN_SEKUNDEN)
        _wecker.clear()


def verarbeite_einen():
    """Laedt den naechsten wartenden Upload hoch. False, wenn keiner wartet."""
    schlange = db.cloud_warteschlange()
    if not schlange:
        return False
    eintrag = schlange[0]
    try:
        lade_hoch(eintrag)
    except Exception as err:
        # Der Thread darf nicht sterben, und ein Eintrag, der dauerhaft auf
        # "wartet" stuende, wuerde hier im Kreis laufen.
        _fehlschlag(eintrag["id"], f"Unerwarteter Fehler: {err}")
    return True


# --- Upload --------------------------------------------------------------

def lade_hoch(eintrag):
    """Laedt eine Aufnahme hoch und schreibt den Zustand fort. Liefert True bei Erfolg."""
    rid = eintrag["id"]
    datei = Path(eintrag.get("output_file") or "")
    if not datei.is_file():
        return _fehlschlag(rid, f"Datei nicht vorhanden: {datei}")
    fehlt = fehlende_angaben() if eingeschaltet() else ["cloud_type"]
    if fehlt:
        return _fehlschlag(rid, "Cloud nicht eingerichtet, es fehlt: "
                                + ", ".join(fehlt))

    ziel = ziel_beschreibung()
    groesse = datei.stat().st_size
    db.update_recording(rid, cloud_state="uploading", cloud_target=ziel,
                        cloud_error=None, cloud_at=zeit.text(zeit.jetzt()))
    print(f"[cloud {rid}] Lade {datei.name} ({format_size(groesse)}) nach "
          f"{ziel}", flush=True)

    letzter_fehler = ""
    for versuch in range(1, VERSUCHE + 1):
        try:
            _rclone_kopie(datei)
        except CloudFehler as err:
            letzter_fehler = str(err)
            print(f"[cloud {rid}] Versuch {versuch}/{VERSUCHE} fehlgeschlagen: "
                  f"{err}", flush=True)
            if versuch < VERSUCHE and _halt.wait(PAUSE_SEKUNDEN):
                break
            continue

        db.update_recording(rid, cloud_state="done", cloud_error=None,
                            cloud_at=zeit.text(zeit.jetzt()))
        print(f"[cloud {rid}] Hochgeladen: {datei.name} nach {ziel}", flush=True)
        return True

    if _halt.is_set():
        # Das Add-on wird beendet. Kein Fehlschlag - nach dem Neustart geht
        # es weiter.
        db.update_recording(rid, cloud_state="queued")
        print(f"[cloud {rid}] Upload unterbrochen, wird nach dem Neustart "
              f"wiederholt", flush=True)
        return False
    return _fehlschlag(rid, letzter_fehler)


def _fehlschlag(rid, meldung):
    db.update_recording(rid, cloud_state="failed", cloud_error=meldung,
                        cloud_at=zeit.text(zeit.jetzt()))
    print(f"[cloud {rid}] FEHLGESCHLAGEN: {meldung}", flush=True)
    return False


def _rclone_kopie(datei):
    if config.CLOUD_TYPE == "rclone":
        konfig = Path(config.CLOUD_CONFIG)
        ziel = f"{config.CLOUD_REMOTE}:{config.CLOUD_PATH}"
    else:
        konfig = _schreibe_konfiguration()
        ziel = f"{_EIGENER_REMOTE}:{config.CLOUD_PATH}"

    befehl = config.RCLONE + [
        "copy", str(datei), ziel,
        "--config", str(konfig),
        "--retries", "1",
        "--log-level", "ERROR",
    ]
    if config.CLOUD_BWLIMIT_KBYTE:
        befehl += ["--bwlimit", f"{config.CLOUD_BWLIMIT_KBYTE}k"]

    grenze = _laufzeitgrenze(datei.stat().st_size)
    try:
        ergebnis = subprocess.run(befehl, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=grenze)
    except FileNotFoundError:
        raise CloudFehler("rclone ist nicht installiert.") from None
    except subprocess.TimeoutExpired:
        raise CloudFehler(f"rclone kam in {grenze // 60} Minuten nicht zum "
                          f"Ende und wurde abgebrochen.") from None
    except OSError as err:
        raise CloudFehler(f"rclone liess sich nicht starten: {err}") from None

    # Wie bei ffmpeg zaehlt der Rueckgabewert. rclones Meldungen enthalten
    # nicht verlaesslich ein Wort wie "error".
    if ergebnis.returncode != 0:
        raise CloudFehler(_letzte_zeile(ergebnis.stderr)
                          or f"rclone endete mit Code {ergebnis.returncode}.")


def _schreibe_konfiguration():
    """Erzeugt die rclone.conf fuer WebDAV oder S3 aus den Add-on-Optionen.

    Wird vor jedem Upload neu geschrieben. Die Optionen aendern sich nur mit
    einem Neustart, aber so kann die Datei nie veraltet sein.
    """
    if config.CLOUD_TYPE == "webdav":
        abschnitt = {
            "type": "webdav",
            "url": config.CLOUD_URL,
            "vendor": "other",
            "user": config.CLOUD_USER,
            "pass": _verschleiere(config.CLOUD_PASSWORD),
        }
    else:
        # S3-Schluessel stehen bei rclone im Klartext, nur WebDAV-Passwoerter
        # werden verschleiert.
        abschnitt = {
            "type": "s3",
            "provider": "Other",
            "endpoint": config.CLOUD_URL,
            "access_key_id": config.CLOUD_USER,
            "secret_access_key": config.CLOUD_PASSWORD,
        }

    parser = configparser.ConfigParser(interpolation=None)
    parser[_EIGENER_REMOTE] = abschnitt
    pfad = config.DATA_DIR / "rclone-cloud.conf"
    pfad.parent.mkdir(parents=True, exist_ok=True)
    # newline="": sonst schreibt Windows CRLF, siehe CLAUDE.md.
    with open(pfad, "w", encoding="utf-8", newline="") as datei:
        parser.write(datei)
    try:
        os.chmod(pfad, 0o600)
    except OSError:
        pass
    return pfad


def _verschleiere(passwort):
    """rclone erwartet Passwoerter in seiner verschleierten Form.

    Das Passwort geht ueber die Standardeingabe hinein, nicht als Argument -
    sonst stuende es in der Prozessliste.
    """
    if passwort in _verschleiert:
        return _verschleiert[passwort]
    try:
        ergebnis = subprocess.run(config.RCLONE + ["obscure", "-"],
                                  input=passwort, capture_output=True,
                                  text=True, encoding="utf-8", timeout=60)
    except FileNotFoundError:
        raise CloudFehler("rclone ist nicht installiert.") from None
    except (OSError, subprocess.TimeoutExpired) as err:
        raise CloudFehler(f"rclone obscure scheiterte: {err}") from None
    wert = ergebnis.stdout.strip()
    if ergebnis.returncode != 0 or not wert:
        raise CloudFehler("Das Passwort liess sich nicht fuer rclone "
                          "aufbereiten: " + (_letzte_zeile(ergebnis.stderr)
                                             or f"Code {ergebnis.returncode}"))
    _verschleiert[passwort] = wert
    return wert


def _laufzeitgrenze(groesse):
    rate = _MINDESTRATE
    if config.CLOUD_BWLIMIT_KBYTE:
        # Mit gedrosseltem Upload darf es entsprechend laenger dauern.
        rate = min(rate, config.CLOUD_BWLIMIT_KBYTE * 1024 // 2)
    return int(min(_HOECHSTZEIT, max(_MINDESTZEIT, groesse / max(rate, 1))))


def _letzte_zeile(text):
    zeilen = [z.strip() for z in (text or "").splitlines() if z.strip()]
    return zeilen[-1] if zeilen else ""


def _ohne_zugang(url):
    """Entfernt Benutzer und Passwort, falls jemand sie in die Adresse schrieb."""
    try:
        teile = urlsplit(url or "")
        if teile.username or teile.password:
            netloc = teile.hostname or ""
            if teile.port:
                netloc += f":{teile.port}"
            teile = teile._replace(netloc=netloc)
        return urlunsplit(teile)
    except ValueError:
        return "(Adresse unlesbar)"
