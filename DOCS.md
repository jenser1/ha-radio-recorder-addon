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
