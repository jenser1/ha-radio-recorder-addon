# Radio Recorder für Home Assistant

Add-on, das Internetradio zeitgesteuert mit FFmpeg aufzeichnet - manuell oder
nach Zeitplan, bis zu 24 Stunden am Stück.

* Oberfläche über das Sidebar-Panel (Ingress), keine zusätzliche Einrichtung
* Zeitpläne nach Wochentag und Uhrzeit, pausierbar
* Angefangene Aufnahmen überstehen einen Neustart des Add-ons
* Fehlgeschlagene Aufnahmen werden mit Ursache angezeigt

Ausführliche Beschreibung: siehe [DOCS.md](DOCS.md).

## Entwicklung

```
python tests/test_phase0.py
```

Der Rauchtest braucht kein ffmpeg - der Aufruf wird durch einen Platzhalter
ersetzt, der Segmente schreibt und sich abbrechen lässt.
