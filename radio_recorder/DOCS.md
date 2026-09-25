# Radio Recorder

## Installation

Den Ordner `radio_recorder` nach `/addons/radio_recorder` kopieren, den
Add-on-Store neu laden und das Add-on installieren.

Beim Update von Version 0.2.0 werden bestehende Zeitpläne aus
`/data/jobs.json` automatisch in die neue Datenbank übernommen. Die alte
Datei bleibt als `jobs.json.uebernommen` liegen.

## Optionen

| Option | Bedeutung |
|---|---|
| `output_dir` | Zielordner für fertige Aufnahmen. Vorgabe `/media/Musick/Radioaufnahmen`. |
| `default_duration_hours` | Vorbelegung der Stunden in den Formularen. |
| `default_duration_minutes` | Vorbelegung der Minuten. |
| `segment_minutes` | Länge der Zwischenstücke während der Aufnahme (siehe unten). Vorgabe 10. |
| `min_free_mb` | So viel Platz soll frei bleiben. Wird vor dem Start geprüft und während der Aufnahme überwacht. Vorgabe 500. |
| `work_dir` | Optional. Ablage der Zwischenstücke. Ohne Angabe `/data/work`. |

## Sender

Sender werden in der Oberfläche unter **Sender** verwaltet. Zwei Wege:

**Suche.** Das Suchfeld fragt [radio-browser.info](https://www.radio-browser.info)
ab, ein offenes Verzeichnis mit rund 50.000 Internetradios. Keine Anmeldung,
kein Schlüssel; das Add-on braucht dafür Zugang zum Internet. Ein Treffer wird
erst übernommen, wenn er ausgewählt wurde.

**Von Hand.** Name und Stream-Adresse eintragen. Bleibt der Name leer, wird er
aus dem Stream gelesen (`icy-name`).

In beiden Fällen wird der Stream einmal mit `ffprobe` geprüft, um Codec und
Bitrate zu ermitteln. Das dauert ein paar Sekunden. Antwortet der Stream
nicht, wird der Sender trotzdem angelegt - dann gilt vorerst MP3 mit
192 kbit/s, und die Prüfung lässt sich später über 🔄 wiederholen.

### Warum der Codec wichtig ist

Aufgenommen wird mit `-c:a copy`, der Ton wird also unverändert
durchgereicht. Steckt im Stream AAC, muss auch die Datei ein AAC-Behältnis
sein - eine `.mp3` mit AAC-Inhalt wäre unbrauchbar. Die Endung richtet sich
deshalb nach dem erkannten Codec:

| Codec | Datei |
|---|---|
| mp3 | `.mp3` |
| aac, aac_latm | `.aac` |
| vorbis | `.ogg` |
| opus | `.opus` |
| flac | `.flac` |

Ein Sender lässt sich nicht löschen, solange ein Zeitplan ihn verwendet.
Bereits erstellte Aufnahmen bleiben davon unberührt.

## Zeitpläne

Die Dauer lässt sich auf zwei Arten angeben:

* **Dauer** in Stunden und Minuten.
* **Endzeit** als Uhrzeit. Liegt sie vor der Startzeit, wird bis zum nächsten
  Tag aufgenommen - „22:00 bis 02:00" ergibt vier Stunden.

Dazu kommen **Vorlauf** und **Nachlauf** in Minuten, falls eine Sendung
erfahrungsgemäß etwas früher beginnt oder später endet. Der Vorlauf zieht den
Start vor, der Nachlauf verlängert die Aufnahme. Reicht der Vorlauf über
Mitternacht zurück, wandert der Wochentag mit: „Montag 00:01" mit fünf
Minuten Vorlauf startet sonntags um 23:56.

## Bibliothek

Unter **Bibliothek** stehen alle abgeschlossenen Aufnahmen mit Abspielleiste,
Download und Löschen. Gelöscht wird nach Rückfrage, und zwar endgültig - es
gibt keinen Papierkorb.

Ausgeliefert wird ausschließlich, was im eingestellten Zielordner liegt.
Zeigt ein Eintrag auf eine Datei außerhalb, wird sie nicht ausgeliefert.

### Vorhandene Dateien aufnehmen

Beim Start durchsucht das Add-on den Zielordner nach Aufnahmen, die noch
nicht in der Liste stehen, und trägt sie nach. Das betrifft Dateien aus einer
früheren Fassung, aus einer anderen Installation oder von Hand
hineinkopierte. Der Knopf **Zielordner durchsuchen** stößt das jederzeit
erneut an.

Solche Einträge tragen die Kennzeichnung **gefunden**. Ermittelt werden:

* **Beginn und Bezeichnung** aus dem Dateinamen, sofern er dem Muster
  `Sender_Bezeichnung_JJJJ-MM-TT_SS-MM-SS` folgt. Andernfalls dient der
  Zeitpunkt der Datei als Beginn und der Dateiname als Bezeichnung.
* **Spieldauer** über `ffprobe`.

Übersprungen werden leere Dateien und solche, die in der letzten Minute
geschrieben wurden - die könnten noch unfertig sein.

Der erste Suchlauf liest jede Datei einmal an und kann bei vielen Aufnahmen
etwas dauern. Er läuft nebenher, die Oberfläche ist sofort bedienbar.

## Wie eine Aufnahme abläuft

Während der Aufnahme wird nicht direkt in die Zieldatei geschrieben, sondern
in kurze Segmente unter `/data/work/<id>/`. Erst am Ende werden sie ohne
Neukodierung zu einer Datei im Zielordner zusammengefügt.

Das hat zwei Vorteile:

* Bricht das Add-on ab oder wird es aktualisiert, ist höchstens das
  angefangene Segment betroffen.
* Nach dem Neustart wird die Aufnahme fortgesetzt. Maßgeblich ist dabei die
  geplante **Endzeit**, nicht die Restdauer - die Aufnahme endet also zur
  richtigen Uhrzeit. In der Datei fehlt dann genau die Zeit, in der das
  Add-on nicht lief.

Bricht der Stream mitten in der Aufnahme weg, wird bis zu zehnmal neu
verbunden, solange die Endzeit noch nicht erreicht ist. Lässt sich ffmpeg
gar nicht starten, wird sofort abgebrochen und der Grund angezeigt.

## Lange Aufnahmen

Aufnahmen bis 24 Stunden am Stück sind möglich. Zu beachten ist dabei der
Platzbedarf - bei 192 kbit/s sind das rund **86 MB je Stunde**:

| Dauer | ungefähre Größe |
|---|---|
| 4 Stunden | 346 MB |
| 8 Stunden | 691 MB |
| 12 Stunden | 1,0 GB |
| 24 Stunden | 2,1 GB |

Liegen Arbeits- und Zielordner auf demselben Datenträger, wird beim
Zusammenfügen kurzzeitig **das Doppelte** belegt: die Zwischenstücke bestehen
noch, während die Zieldatei schon geschrieben wird. Das Add-on rechnet das
ein und lehnt einen Start ab, wenn der Platz nicht reicht. Wie viele Stunden
noch hineinpassen, steht in der Oberfläche unter „Speicher".

Geht der Platz trotzdem während einer laufenden Aufnahme zur Neige, wird
geordnet gestoppt und das bis dahin Aufgenommene gespeichert, statt ffmpeg
mitten im Schreiben scheitern zu lassen.

Der Arbeitsordner liegt bewusst im lokalen Add-on-Speicher: so übersteht eine
laufende Aufnahme auch einen Ausfall des Netzlaufwerks. Wer dort wenig Platz
hat, kann ihn über `work_dir` verlegen - dann allerdings ohne diesen Schutz.

## Zeitzone

Das Add-on übernimmt die Zeitzone von Home Assistant und setzt sie für
Python und den Scheduler ausdrücklich. Die aktuell verwendete Zeitzone steht
unten in der Oberfläche und unter `/health`. Steht dort „nicht gesetzt",
laufen Zeitpläne in UTC - dann die Zeitzone in Home Assistant prüfen
(Einstellungen → System → Allgemein).

## Zustände einer Aufnahme

| Zustand | Bedeutung |
|---|---|
| läuft | Aufnahme aktiv |
| fertig | regulär bis zur geplanten Endzeit gelaufen |
| abgebrochen | vorzeitig gestoppt, Teilaufnahme wurde gespeichert |
| fehlgeschlagen | keine verwertbaren Daten, Ursache wird angezeigt |

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
