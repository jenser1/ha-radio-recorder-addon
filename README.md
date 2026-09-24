# Radio Recorder für Home Assistant

Add-on, das Internetradio zeitgesteuert mit FFmpeg aufzeichnet - manuell oder
nach Zeitplan, bis zu 24 Stunden am Stück.

* Oberfläche über das Sidebar-Panel (Ingress), keine zusätzliche Einrichtung
* Beliebig viele Sender, wahlweise über die Suche in radio-browser.info
  oder von Hand eingetragen
* Codec und Bitrate werden aus dem Stream ermittelt, die Dateiendung passt
  sich danach
* Zeitpläne nach Wochentag, wahlweise über Dauer oder Endzeit, mit Vor- und
  Nachlauf, pausierbar
* Bibliothek mit Abspielen, Herunterladen und Löschen
* Angefangene Aufnahmen überstehen einen Neustart des Add-ons
* Speicherplatz wird vor dem Start geprüft und während der Aufnahme überwacht

Ausführliche Beschreibung: siehe [DOCS.md](DOCS.md).

## Entwicklung

```bash
python tests/test_phase0.py && python tests/test_phase1.py
```

Die Rauchtests brauchen weder ffmpeg noch Internet: ffmpeg und ffprobe werden
durch Platzhalter in `tests/` ersetzt, die Sendersuche wird abgefangen.

**Wichtig:** Alle Dateien müssen Unix-Zeilenenden behalten. Mit CRLF wird aus
der ersten Zeile von `run.sh` ein `bashio\r`, und das Add-on startet nicht
mehr. Der Rauchtest prüft das mit.
