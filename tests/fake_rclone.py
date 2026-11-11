"""Platzhalter fuer rclone im Test.

Kann zweierlei, wie das Original:
  * obscure -          liest das Passwort von der Standardeingabe und gibt
                       eine verschleierte Fassung aus.
  * copy QUELLE ZIEL   legt die Datei unter RR_FAKE_RCLONE_CLOUD ab - der
                       Ordner spielt die Cloud, je Remote ein Unterordner.

RR_FAKE_RCLONE steuert das Kopieren:
  ok             (Vorgabe) klappt
  fehler         Anmeldung abgelehnt, Code 1
  still          Code 1 ohne jede Meldung
  einmal_fehler  erster Aufruf scheitert, jeder weitere klappt; der Zaehler
                 steht in RR_FAKE_RCLONE_ZAEHLER

Ist RR_FAKE_RCLONE_ERNEUERN gesetzt, schreibt ein erfolgreicher Upload wie
das echte rclone einen erneuerten Zugangsschluessel in die Datei hinter
--config zurueck ("token = neu").

Jeder Aufruf wird als JSON-Zeile nach RR_FAKE_RCLONE_LOG geschrieben, damit
der Test die Argumente pruefen kann.
"""

import json
import os
import re
import shutil
import sys
from pathlib import Path


def _protokoll(args):
    ziel = os.environ.get("RR_FAKE_RCLONE_LOG")
    if ziel:
        with open(ziel, "a", encoding="utf-8", newline="") as datei:
            datei.write(json.dumps(args) + "\n")


def _zaehle():
    pfad = Path(os.environ["RR_FAKE_RCLONE_ZAEHLER"])
    bisher = int(pfad.read_text(encoding="utf-8") or 0) if pfad.exists() else 0
    with open(pfad, "w", encoding="utf-8", newline="") as datei:
        datei.write(str(bisher + 1))
    return bisher


def main():
    args = sys.argv[1:]
    _protokoll(args)

    if args[:2] == ["obscure", "-"]:
        passwort = sys.stdin.read()
        print("versteckt-" + passwort[::-1].encode("utf-8").hex())
        return 0

    if args and args[0] == "copy":
        quelle, ziel = Path(args[1]), args[2]
        modus = os.environ.get("RR_FAKE_RCLONE", "ok")
        if modus == "einmal_fehler":
            modus = "fehler" if _zaehle() == 0 else "ok"

        if modus == "fehler":
            # Bewusst ohne "error" oder "failed": der Aufrufer soll den
            # Rueckgabewert auswerten, nicht den Wortlaut.
            sys.stderr.write("Couldn't connect to cloud.example: "
                             "401 Unauthorized\n")
            return 1
        if modus == "still":
            return 1

        remote, _, pfad = ziel.partition(":")
        ordner = Path(os.environ["RR_FAKE_RCLONE_CLOUD"]) / remote / pfad
        ordner.mkdir(parents=True, exist_ok=True)
        shutil.copy2(quelle, ordner / quelle.name)

        if os.environ.get("RR_FAKE_RCLONE_ERNEUERN") and "--config" in args:
            # Scheitert hier das Schreiben, ist die Datei nicht beschreibbar -
            # genau das, was beim nur lesbar eingebundenen /share passiert.
            konfig = Path(args[args.index("--config") + 1])
            text = konfig.read_text(encoding="utf-8")
            with open(konfig, "w", encoding="utf-8", newline="") as datei:
                datei.write(re.sub(r"token = .*", "token = neu", text))
        return 0

    sys.stderr.write(f"Unbekannter Aufruf: {args}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
