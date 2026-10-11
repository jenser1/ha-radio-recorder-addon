<p align="center">
  <img src="radio_recorder/logo.png" alt="ha-radio-recorder" width="320">
</p>

<h1 align="center">Radio Recorder – Add-on für Home Assistant</h1>

<p align="center">
Zeichnet Internetradio zeitgesteuert mit FFmpeg auf – manuell oder nach
Zeitplan, bis zu 24 Stunden am Stück.
</p>

![Version](https://img.shields.io/badge/Version-0.7.0-blue)
![Lizenz](https://img.shields.io/badge/Lizenz-MIT-green)
[![Erstellt mit Claude Code](https://img.shields.io/badge/Erstellt%20mit-Claude%20Code-d97757)](https://claude.com/claude-code)

## Installation

1. In Home Assistant: **Einstellungen → Add-ons → Add-on-Store**
2. Oben rechts das **⋮-Menü → Repositories**
3. Diese Adresse eintragen:

   ```
   https://github.com/jenser1/ha-radio-recorder-addon
   ```

4. Den Store neu laden. **Radio Recorder** erscheint als neues Add-on und
   lässt sich installieren.

Updates kommen danach wie bei jedem anderen Add-on über den Store.

## Was es kann

* Oberfläche über das Sidebar-Panel (Ingress), keine zusätzliche Einrichtung
* Beliebig viele Sender, über die Suche in radio-browser.info oder von Hand
* Codec und Bitrate werden aus dem Stream ermittelt, die Dateiendung richtet
  sich danach
* Zeitpläne nach Wochentag, wahlweise über Dauer oder Endzeit, mit Vor- und
  Nachlauf, pausierbar
* Bibliothek mit Abspielen, Herunterladen und Löschen; vorhandene
  Dateien im Zielordner werden von selbst aufgenommen
* Angefangene Aufnahmen überstehen einen Neustart des Add-ons
* Speicherplatz wird vor dem Start geprüft und während der Aufnahme überwacht

Ausführliche Beschreibung: [radio_recorder/DOCS.md](radio_recorder/DOCS.md) ·
Änderungen: [CHANGELOG.md](radio_recorder/CHANGELOG.md)

Updates laufen über die Versionsnummer in `config.yaml`: steht dort eine
höhere als die installierte, bietet Home Assistant das Update an. Eigene
GitHub-Releases sind dafür nicht nötig.

## Aufbau des Repositories

```
├── repository.yaml          Kennzeichnet das Repo als Add-on-Repository
├── radio_recorder/          Das Add-on selbst
│   ├── config.yaml          Optionen und Berechtigungen
│   ├── Dockerfile           Abbild auf Alpine-Basis mit ffmpeg
│   ├── run.sh               Startskript (bashio)
│   ├── app.py               Einstiegspunkt
│   ├── DOCS.md              Dokumentation im Add-on-Store
│   ├── CHANGELOG.md         Änderungsverlauf, von HA beim Update gezeigt
│   ├── icon.png             Symbol in der Add-on-Liste (256×256)
│   ├── logo.png             Logo auf der Add-on-Seite
│   └── radio_recorder/      Python-Paket
├── tests/                   Rauchtests
└── legacy/                  Dateien einer früheren Fassung, nicht mehr aktiv
```

## Entwicklung

```bash
python tests/test_phase0.py && python tests/test_phase1.py
```

Die Rauchtests brauchen weder ffmpeg noch Internet: ffmpeg und ffprobe werden
durch Platzhalter in `tests/` ersetzt, die Sendersuche wird abgefangen.

**Wichtig:** Alle Dateien müssen Unix-Zeilenenden behalten. Mit CRLF wird aus
der ersten Zeile von `run.sh` ein `bashio\r`, und das Add-on startet nicht
mehr. Der Rauchtest prüft das mit, `.gitattributes` erzwingt es.

## Unterstützen

Das Add-on ist kostenlos und bleibt es. Wenn es dir nützt und du etwas
zurückgeben möchtest:

[![Spenden über PayPal](https://img.shields.io/badge/Spenden-PayPal-00457C?logo=paypal&logoColor=white)](https://paypal.me/jenser1)

→ [paypal.me/jenser1](https://paypal.me/jenser1)

## Entstehung

Entwickelt mit [Claude Code](https://claude.com/claude-code). Die
Commit-Historie zeigt den Weg von der ersten Fassung bis hierher, samt der
Fehler, die unterwegs gefunden wurden.

## Lizenz

[MIT](LICENSE)

## Rechtlicher Hinweis

Mitschnitte fürs eigene Archiv sind in Deutschland als Privatkopie gedeckt
(§ 53 UrhG). Weitergabe oder Veröffentlichung der Aufnahmen ist es nicht.
