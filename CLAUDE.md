# Arbeitsgrundlage für dieses Projekt

Kurzfassung dessen, was man wissen muss, bevor man hier etwas ändert.
Besonders der Abschnitt **Fallstricke** — jeder Punkt darin hat in diesem
Projekt schon einmal Schaden angerichtet.

Angaben zur jeweiligen Installation und Entwicklungsumgebung stehen in
`CLAUDE.local.md`. Die Datei liegt bewusst nicht im Repository.

## Was das ist

Home-Assistant-Add-on, das Internetradio zeitgesteuert mit FFmpeg
aufzeichnet. Oberfläche über Ingress, Flask, SQLite.

* Repository: https://github.com/jenser1/ha-radio-recorder-addon
* Aktuelle Fassung: **0.7.3**, Schema-Stand der Datenbank: **5**

## Aufbau

```
repository.yaml              macht das Repo zum Add-on-Repository
radio_recorder/              das Add-on
  config.yaml                Optionen; version: steuert HA-Updates
  CHANGELOG.md               zeigt HA beim Update an
  Dockerfile, run.sh, app.py
  icon.png, logo.png         vom Supervisor aus dem Ordner gelesen
  radio_recorder/            Python-Paket
    config.py    Einstellungen aus Umgebungsvariablen
    db.py        SQLite, Schema-Stand und Migration
    recorder.py  ffmpeg-Steuerung, Segmente, Platzprüfung
    scheduler.py APScheduler, Endzeit, Vor-/Nachlauf
    zeit.py      Zeitpunkte mit Zeitzone, Umstellungsnacht
    probe.py     ffprobe: Codec, Bitrate, Spieldauer
    metadata.py  ICY-Titel auswerten
    directory.py radio-browser.info
    library.py   Zielordner nach Aufnahmen durchsuchen
    web.py       Flask, alle Routen
tests/                       Rauchtests, brauchen kein ffmpeg
legacy/                      alte Fassung, nicht mehr aktiv
```

## Entwickeln und Testen

```bash
python tests/test_phase0.py && python tests/test_phase1.py && python tests/test_phase3.py
```

248 Prüfungen (82 + 105 + 61). **Immer alle drei laufen lassen**, auch bei
kleinen Änderungen — der Recorder hängt an allem.

ffmpeg und ffprobe werden durch `tests/fake_ffmpeg.py` und
`tests/fake_ffprobe.py` ersetzt, gesteuert über Umgebungsvariablen
(`RR_FAKE_TITEL`, `RR_FAKE_VORLAUF`, `RR_FAKE_PROBE`, `RR_FAKE_FAIL`,
`RR_FAKE_HAENGT`).
Dadurch laufen die Tests ohne ffmpeg und ohne Internet, auch in der CI.

Echtes ffmpeg-Verhalten lässt sich damit nicht prüfen. Alles, was daran
hängt — Titelmeldungen, Codecs, Zusammenfügen —, muss auf einem laufenden
Home-Assistant-System nachgesehen werden. Das Add-on schreibt zu solchen
Dingen ausdrücklich ins Protokoll, weil die Oberfläche es nur kurzlebig
anzeigt.

## Fallstricke

**Zeilenenden müssen LF bleiben.** Mit CRLF wird die erste Zeile von
`run.sh` zu `bashio\r`, und das Add-on startet überhaupt nicht — s6 meldet
nur `exec: fatal: unable to exec bashio`. Das ist schon einmal passiert.
Ursache war `pathlib.write_text()` unter Windows: **immer**
`open(..., newline="")` verwenden. `.gitattributes` erzwingt LF, der
Rauchtest prüft es mit (nur Textdateien, in PNG-Daten kommt `\r\n`
zufällig vor).

**Zeitpunkte nie ohne Zeitzone und nie mit `+`/`-` vergleichen.** Alles
Zeitliche läuft über `zeit.py`. Zwei Gründe: Eine Uhrzeit ohne Zone weiß
nicht, wie lang „zwei Stunden später" ist — in der Umstellungsnacht ist das
falsch (Fehler aus 0.7.2). Und Python ignoriert beim Subtrahieren und
Vergleichen den Versatz, wenn beide Zeitpunkte **dasselbe** `tzinfo`-Objekt
tragen; `ZoneInfo` gibt pro Zone immer dasselbe heraus. `a - b` rechnet dann
wieder auf dem Zifferblatt, und 02:30 MESZ gilt als derselbe Zeitpunkt wie
02:30 MEZ. Deshalb `zeit.sekunden_bis`, `zeit.sekunden_zwischen`,
`zeit.minuten_zwischen`, `zeit.plus_minuten` verwenden — die gehen über UTC.
Aus dem gleichen Grund normalisiert `zeit.ortszeit` über UTC:
`astimezone` in dieselbe Zone gibt den Zeitpunkt unverändert zurück.

**Dauer und Endzeit sind nicht dasselbe.** Ein über die Endzeit erfasster
Zeitplan fragt `scheduler.laufzeit_minuten` beim Start nach der wirklichen
Dauer; über die Dauer erfasste bleiben unberührt. Die Obergrenze im Recorder
liegt deshalb bei 25 Stunden, die der Eingabe bei 24.

**ffmpegs `-t` zählt Spielzeit, nicht Uhrzeit.** Server schicken beim
Verbinden einige Sekunden am Stück. ffmpeg ist dadurch vor der Uhr fertig.
Wer das als Abbruch wertet, baut bei jeder Aufnahme überflüssig neu auf
(Fehler aus 0.7.1).

**Positionen in der Datei nie aus der Uhrzeit ableiten.** Derselbe
Pufferstoß und Lücken durch Wiederverbindungen verschieben alles.
Maßgeblich ist ffmpegs `-progress pipe:1` (`out_time_us`). `out_time_ms`
wird bewusst übergangen, etliche Fassungen liefern dort Mikrosekunden.

**Titelmeldungen gibt es nur bei `-loglevel verbose`.** Mit `warning`
erscheinen sie nicht. Dazu `-nostats`, sonst flutet der Fortschritt die
Ausgabe.

**Fehler am Rückgabewert erkennen, nicht am Wortlaut.** „Server returned
404 Not Found" enthält weder „error" noch „failed".

**Eingaben ablehnen statt zurechtbiegen.** Aus „25 Stunden" wurden einmal
stillschweigend 24. Werte außerhalb des Bereichs geben eine Meldung.

**`hidden` wird von eigenen `display`-Angaben überstimmt.** Im CSS steht
deshalb `[hidden]{display:none !important}`.

**Größenangaben nur über `recorder.format_size`.** Eine zweite Fassung in
`web.py` rechnete falsch und zeigte 7,2 TB als „7346,3 TB".

**Windows reicht leere Umgebungsvariablen nicht an Kindprozesse weiter.**
In Tests dafür das Wort `KEINE` verwenden. Außerdem braucht `Popen` dort
rund 17 Sekunden, um einen fehlenden Befehl abzulehnen — unter Linux
geschieht das sofort.

**Datenbank-Migration.** `db.SCHEMA_VERSION` erhöhen und die Spalte in
`_upgrade()` nachziehen. `CREATE TABLE IF NOT EXISTS` ändert bestehende
Tabellen nicht. Es gibt Installationen mit echten Zeitplänen und Aufnahmen
— jede Migration muss diese überleben, nicht nur eine frische Datenbank.

**Der Arbeitsordner liegt bewusst lokal** (`/data/work`), auch wenn das Ziel
ein Netzlaufwerk ist. So übersteht eine laufende Aufnahme einen
Netzwerkausfall; nur das abschließende Zusammenfügen würde scheitern. Über
die Option `work_dir` lässt sich das umdrehen.

**Updates laufen über `version:` in `config.yaml`.** GitHub-Releases spielen
keine Rolle. Jeder Push nach `main` mit erhöhter Nummer ist bereits die
Veröffentlichung. Tags werden zusätzlich gesetzt, rein für Menschen.

## Stand der Phasen

| Phase | Inhalt | Stand |
|---|---|---|
| 0 | Fundament: Zeitzone, SQLite, neustartsichere Aufnahmen, Platzprüfung | fertig, im Betrieb bestätigt |
| 1 | Sender, Codec-Erkennung, Endzeit, Vor-/Nachlauf, Bibliothek | fertig, im Betrieb bestätigt |
| 2 | Speicherziele | NAS läuft über HA-Netzwerkspeicher; Aufräumregeln und Cloud-Upload offen |
| 3 | Aufnahmen in Einzeltitel zerlegen | Stufen 1–2 fertig, 3–4 **blockiert**, siehe unten |
| 4 | MQTT-Anbindung an Home Assistant | offen |
| 5 | Podcasts, Statistik, Programmführer | offen |

## Offener Punkt: Titelerkennung

Phase 3 sollte Aufnahmen anhand der ICY-Metadaten in Einzeltitel zerlegen.
Technisch funktioniert das Mitschreiben: ffmpeg meldet Titelwechsel als
`Metadata update for StreamTitle: …`, sie werden mit ihrer Position in
`track_marks` abgelegt und in der Bibliothek angezeigt.

**Der Hauptstrom von Sunshine Live liefert aber keine Titel.** Zwei
Testaufnahmen über je 29 Minuten ergaben zusammen vier Meldungen:

* 3× `SUNSHINE LIVE - Simulcast` — die Senderkennung
* 1× `Dance Department - Armin Van Buuren` — ein Sendungsname. Die
  Aufteilung in Interpret und Titel liegt hier verkehrt herum.

Gelaufen sind in der Zeit etwa 15 Lieder, gemeldet wurde keines. Der Strom
überträgt das UKW-Programm („Simulcast"), und solche Ströme führen meist
keine Titelinformation. Filtern hilft nicht, wenn nichts da ist.

**Nächster Schritt:** Die Spartenkanäle prüfen (Classics, Techno, 90er,
Eurodance, House …). Automatisierte Playlisten führen häufig sehr wohl
Titel mit. Der Knopf 🎵 in der Senderliste beantwortet das je Sender in
45 Sekunden. Erst wenn dort echte Liedtitel ankommen, lohnt sich Stufe 3
(Aussortieren von Senderkennung und Werbung) und Stufe 4 (Schneiden,
Beschriften, Titelbild).

Entschieden ist bereits: zerlegt wird erst auf Knopfdruck, die
Originalaufnahme bleibt erhalten, Ablage in einem Ordner je Aufnahme,
Titelbilder über das Cover Art Archive.

## Konventionen

* Oberfläche, Dokumentation und Kommentare auf **Deutsch**; Bezeichner im
  Code gemischt, neue Hilfsfunktionen deutsch benannt.
* Kommentare erklären das **Warum**, nicht das Was.
* Commit-Nachrichten deutsch, ohne Umlaute, mit Begründung im Rumpf.
* Jede Verhaltensänderung bekommt eine Prüfung im passenden Rauchtest.
* Vor dem Hochladen fragen, wenn es nicht ausdrücklich freigegeben wurde.
* Keine Angaben zur eigenen Installation in dieser Datei — die gehören in
  `CLAUDE.local.md`.
