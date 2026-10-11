# Änderungsverlauf

Alle nennenswerten Änderungen an diesem Add-on.
Die Versionsnummer in `config.yaml` steuert, wann Home Assistant ein
Update anbietet - eigene GitHub-Releases braucht es dafür nicht.

## Version 0.7.1

- Jede Aufnahme baute gegen Ende überflüssig neu auf: Server schicken beim
  Verbinden einige Sekunden am Stück, dadurch ist ffmpeg mit seiner
  Spielzeit früher durch als die Uhr. Das galt als Abbruch und löste einen
  Verbindungsversuch mit 15 Sekunden Pause aus. Jetzt zählt die erreichte
  Spielzeit.

## Version 0.7.0

- Gemeldete Titel werden während der Aufnahme mitgeschrieben und in der
  Bibliothek angezeigt, samt ihrer Stelle in der Datei
- Eigenes Symbol und Logo
- Dieser Änderungsverlauf, den Home Assistant beim Update anzeigt
- `startup`, `boot` und `ingress_port` aus der Konfiguration entfernt, sie
  standen auf den ohnehin geltenden Vorgaben

## Version 0.6.0

- Titelerkennung je Sender prüfbar (Knopf 🎵 in der Senderliste)
- Grundlage für das spätere Zerlegen von Aufnahmen in Einzeltitel

## Version 0.5.0

- Der Zielordner wird beim Start nach Aufnahmen durchsucht, die noch nicht
  in der Bibliothek stehen; solche Einträge sind als **gefunden**
  gekennzeichnet
- Knopf **Zielordner durchsuchen** für einen erneuten Durchlauf
- Spieldauer gefundener Aufnahmen wird über `ffprobe` ermittelt
- Größenangaben ab einem Terabyte waren um den Faktor 1024 zu hoch; ein
  Netzlaufwerk mit 7,2 TB wurde als „7346,3 TB" angezeigt
- Ergebnis jeder Stream-Prüfung steht jetzt auch im Protokoll
- Ungeprüfte Sender heißen „noch nicht geprüft" statt „?"
- Arbeitsordner wird mehrfach zu räumen versucht und gemeldet, wenn er
  liegenbleibt

## Version 0.4.0

- Beliebig viele Sender, verwaltet in der Datenbank statt fest im Code
- Sendersuche über radio-browser.info
- Codec und Bitrate werden aus dem Stream ermittelt, die Dateiendung richtet
  sich danach
- Zeitpläne wahlweise über Dauer oder Endzeit, mit Vor- und Nachlauf
- Bibliothek mit Abspielen, Herunterladen und Löschen
- Oberfläche auf drei Seiten aufgeteilt
- Eingaben außerhalb des zulässigen Bereichs werden abgelehnt statt
  stillschweigend gekürzt

Bestehende Zeitpläne und Aufnahmen werden beim Update übernommen; der bisher
fest eingebaute Sender wird als erster Eintrag angelegt.

## Version 0.3.1

- Platzbedarf wird vor dem Start geprüft, inklusive des doppelten Bedarfs
  beim Zusammenfügen auf einem gemeinsamen Datenträger
- Platzüberwachung während langer Aufnahmen mit geordnetem Stopp
- Speicherübersicht in der Oberfläche mit Reichweite in Stunden
- neue Optionen `min_free_mb` und `work_dir`

## Version 0.3.0

- Zeitpläne und Aufnahmen in SQLite statt JSON-Dateien
- Angefangene Aufnahmen überstehen einen Neustart des Add-ons
- Fehlerursachen werden in der Oberfläche angezeigt
- Zeitzone wird ausdrücklich gesetzt und ist nachprüfbar
- Zeitpläne pausierbar, nächster Lauf wird angezeigt
- Übersicht der letzten Aufnahmen
- Startzeit und Wochentage werden geprüft statt blind übernommen
- Code in Module aufgeteilt, Rauchtest ergänzt
