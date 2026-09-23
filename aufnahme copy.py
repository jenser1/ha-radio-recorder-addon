import json
from datetime import datetime, date
import requests
import time
import os
import sys

# Stelle sicher, dass Ausgaben sofort erscheinen (unbuffered)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def log(*args, **kwargs):
    """Log-Funktion die sofort ausgegeben wird"""
    # Unterstützt print() Syntax mit mehreren Argumenten
    message = ' '.join(str(arg) for arg in args) if args else ''
    print(message, **kwargs, flush=True)
    sys.stdout.flush()
    sys.stderr.flush()

def find_music_assistant_path():
    """Findet den Music Assistant Speicherpfad"""
    # Standard-Pfad: /media/Musick (höchste Priorität)
    # Dann andere mögliche Pfade
    possible_paths = [
        "/media/Musick",  # Standard-Speicherpfad (höchste Priorität)
        "/media/musick",
        "/media/Music",
        "/media/music",
        "/config/music",  # Standard Music Assistant Pfad
        "/config/musicassistant",  # Alternative
        "/share/Musick",  # Direkter Share-Name (Music Assistant remote share)
        "/share/musick",
        "/share/music",
        "/share/Music",
        "/share/nasvondu/Musick",
        "/share/nasvondu/musick",
        "/share/nasvondu/music",
        "/share/nasvondu/Music",
        "/mnt/Musick",
        "/mnt/musick",
        "/mnt/nasvondu/Musick",
        "/mnt/nasvondu/musick",
    ]
    
    log("Suche nach Music Assistant Speicherpfad...")
    
    for path in possible_paths:
        if os.path.exists(path):
            log(f"  Gefunden: {path}")
            if os.access(path, os.W_OK):
                log(f"  ✓ Verzeichnis ist beschreibbar")
                return path
            else:
                log(f"  ✗ Verzeichnis ist nicht beschreibbar")
    
    # Suche rekursiv nach Music Assistant Verzeichnissen
    search_roots = ["/config", "/share", "/mnt", "/media"]
    target_names = ["music", "Music", "musick", "Musick", "musicassistant", "MusicAssistant"]
    
    log("  Suche rekursiv nach Music Assistant Verzeichnissen...")
    for root in search_roots:
        if not os.path.exists(root):
            continue
        try:
            for item in os.listdir(root):
                item_path = os.path.join(root, item)
                if os.path.isdir(item_path):
                    if item.lower() in [n.lower() for n in target_names]:
                        log(f"  Gefunden: {item_path}")
                        if os.access(item_path, os.W_OK):
                            log(f"  ✓ Verwendbar: {item_path}")
                            return item_path
        except Exception as e:
            log(f"  Fehler beim Durchsuchen von {root}: {e}")
    
    log("  ✗ Music Assistant Speicherpfad nicht gefunden")
    return None

def find_nas_path():
    """Findet das gemountete NAS-Verzeichnis (Fallback)"""
    # Versuche Music Assistant Pfad zuerst
    ma_path = find_music_assistant_path()
    if ma_path:
        return ma_path
    
    # Falls nicht gefunden, suche nach NAS-Verzeichnissen
    possible_nas_paths = [
        "/share/Musick",
        "/share/musick",
        "/share/music",
        "/share/Music",
    ]
    
    log("Suche nach gemountetem NAS-Verzeichnis (Fallback)...")
    
    for nas_path in possible_nas_paths:
        if os.path.exists(nas_path):
            log(f"  Gefunden: {nas_path}")
            if os.access(nas_path, os.W_OK):
                log(f"  ✓ Verzeichnis ist beschreibbar")
                return nas_path
    
    return None
    
    log("Suche nach gemountetem NAS-Verzeichnis...")
    
    # Prüfe zuerst spezifische Pfade
    for nas_path in possible_nas_paths:
        if os.path.exists(nas_path):
            log(f"  Gefunden: {nas_path}")
            if os.access(nas_path, os.W_OK):
                log(f"  ✓ Verzeichnis ist beschreibbar")
                return nas_path
            else:
                log(f"  ✗ Verzeichnis ist nicht beschreibbar")
    
    # Suche rekursiv in /share, /mnt, /media nach "Musick" oder "musick"
    search_roots = ["/share", "/mnt", "/media"]
    target_names = ["Musick", "musick", "music", "Music", "nasvondu"]
    
    log("  Suche rekursiv in gemounteten Verzeichnissen...")
    for root in search_roots:
        if not os.path.exists(root):
            continue
        try:
            # Durchsuche direktes Unterverzeichnis
            for item in os.listdir(root):
                item_path = os.path.join(root, item)
                if os.path.isdir(item_path):
                    # Prüfe ob es direkt "Musick" oder "musick" ist (höchste Priorität)
                    if item.lower() in ["musick", "music"]:
                        log(f"  Gefunden: {item_path}")
                        if os.access(item_path, os.W_OK):
                            log(f"  ✓ Verwendbar: {item_path}")
                            return item_path
                    # Prüfe ob es nasvondu oder ähnlich ist
                    elif item.lower() in [n.lower() for n in target_names]:
                        log(f"  Gefunden: {item_path}")
                        if os.access(item_path, os.W_OK):
                            # Versuche Musick/musick Unterverzeichnis zu finden
                            for subdir in ["Musick", "musick", "music", "Music"]:
                                sub_path = os.path.join(item_path, subdir)
                                if os.path.exists(sub_path):
                                    if os.access(sub_path, os.W_OK):
                                        log(f"  ✓ Gefunden: {sub_path}")
                                        return sub_path
                            # Falls kein Unterverzeichnis, versuche zu erstellen
                            for subdir in ["Musick", "musick"]:
                                sub_path = os.path.join(item_path, subdir)
                                try:
                                    os.makedirs(sub_path, exist_ok=True)
                                    if os.access(sub_path, os.W_OK):
                                        log(f"  ✓ Erstellt und verwendbar: {sub_path}")
                                        return sub_path
                                except:
                                    pass
        except Exception as e:
            log(f"  Fehler beim Durchsuchen von {root}: {e}")
    
    # Prüfe auch übergeordnete Verzeichnisse
    parent_paths = ["/share/nasvondu", "/mnt/nasvondu", "/media/nasvondu"]
    for parent in parent_paths:
        if os.path.exists(parent) and os.access(parent, os.W_OK):
            log(f"  Gefunden übergeordnetes Verzeichnis: {parent}")
            # Versuche musick/Musick Unterverzeichnis zu erstellen
            for subdir in ["musick", "Musick", "music", "Music"]:
                full_path = os.path.join(parent, subdir)
                try:
                    os.makedirs(full_path, exist_ok=True)
                    if os.access(full_path, os.W_OK):
                        log(f"  ✓ Erstellt und verwendbar: {full_path}")
                        return full_path
                except Exception as e:
                    pass
    
    log("  ✗ Kein NAS-Verzeichnis gefunden")
    log("  HINWEIS: Falls das NAS bereits gemountet ist, prüfen Sie:")
    log("    - /share/Musick")
    log("    - /share/musick")
    log("    - Oder den Mount-Point, den Sie in Supervisor konfiguriert haben")
    return None

log("=" * 50)
log("Radio Recorder gestartet")
log("=" * 50)

# Suche nach gemountetem NAS-Verzeichnis
log("\nSuche nach gemountetem NAS...")
NAS_MOUNT_POINT = find_nas_path()

# Standard-Speicherpfad
if NAS_MOUNT_POINT:
    DEFAULT_SAVE_PATH = NAS_MOUNT_POINT
    log(f"\n✓ Standard-Speicherpfad: {DEFAULT_SAVE_PATH}")
else:
    # Fallback: Versuche /media/Musick zu erstellen, sonst /data
    fallback_path = "/media/Musick"
    try:
        os.makedirs(fallback_path, exist_ok=True)
        if os.access(fallback_path, os.W_OK):
            DEFAULT_SAVE_PATH = fallback_path
            log(f"\n✓ Standard-Speicherpfad erstellt: {DEFAULT_SAVE_PATH}")
        else:
            DEFAULT_SAVE_PATH = '/data'
            log(f"\n⚠ {fallback_path} nicht beschreibbar, verwende: {DEFAULT_SAVE_PATH}")
    except Exception as e:
        DEFAULT_SAVE_PATH = '/data'
        log(f"\n⚠ Konnte {fallback_path} nicht erstellen ({e}), verwende: {DEFAULT_SAVE_PATH}")

# Prüfe verfügbare Mount-Punkte
log("\nVerfügbare Verzeichnisse:")
possible_paths = ['/share', '/mnt', '/media', '/mnt/nas']
for path in possible_paths:
    if os.path.exists(path):
        log(f"  {path} existiert")
        try:
            contents = os.listdir(path)
            log(f"    Inhalt: {contents}")
        except:
            log(f"    (kann nicht gelesen werden)")

log("=" * 50)

with open("/data/options.json") as f:
    cfg = json.load(f)

log(f"\nKonfiguration geladen:")
log(json.dumps(cfg, indent=2))

JOBS_RAW = cfg.get("jobs", [])
JOBS = []

# Home Assistant speichert manchmal jobs als Dictionary statt Liste
if isinstance(JOBS_RAW, dict):
    log("WARNUNG: jobs ist ein Dictionary, versuche zu konvertieren...")
    # Prüfe ob es ein Schema-Dictionary ist (falsche Speicherung)
    if "schema" in JOBS_RAW:
        log("  jobs enthält 'schema' - das ist die Schema-Definition, nicht die Jobs!")
        # Versuche Jobs aus dem Schema zu extrahieren (falls sie dort versteckt sind)
        schema_dict = JOBS_RAW.get("schema", {})
        if isinstance(schema_dict, dict):
            # Prüfe ob die Schema-Werte tatsächlich Job-Daten sind
            if "name" in schema_dict or "stream_url" in schema_dict:
                log("  Schema enthält Job-Daten, versuche zu extrahieren...")
                # Entferne Schema-Metadaten und behalte nur Job-Felder
                job_data = {}
                job_fields = ["name", "stream_url", "save_path", "time_start", "time_end", 
                             "weekdays", "date_start", "date_end"]
                for field in job_fields:
                    if field in schema_dict:
                        value = schema_dict[field]
                        # Wenn es ein Dictionary mit "type" ist, überspringe es
                        if isinstance(value, dict) and "type" in value:
                            continue
                        job_data[field] = value
                if job_data.get("name") or job_data.get("stream_url"):
                    JOBS = [job_data]
                    log(f"  ✓ Job aus Schema extrahiert: {job_data.get('name', 'Unbekannt')}")
        if not JOBS:
            log("  Bitte Jobs in der Add-on-Konfiguration hinzufügen.")
            log("  Anleitung:")
            log("    1. Supervisor → Add-ons → Radio Recorder → Configuration")
            log("    2. Fügen Sie Jobs als Liste hinzu, z.B.:")
            log('       jobs:')
            log('         - name: "Mein Radio"')
            log('           stream_url: "https://..."')
            log('           save_path: "/share/nasvondu/musick"')
            log('           time_start: "10:00"')
            log('           time_end: "11:00"')
    # Prüfe ob es vielleicht ein einzelner Job ist
    elif "name" in JOBS_RAW or "stream_url" in JOBS_RAW:
        log("  jobs scheint ein einzelner Job zu sein, konvertiere zu Liste")
        JOBS = [JOBS_RAW]
    else:
        # Versuche alle Werte zu durchsuchen
        for key, value in JOBS_RAW.items():
            if isinstance(value, dict) and ("name" in value or "stream_url" in value):
                JOBS.append(value)
        if JOBS:
            log(f"  {len(JOBS)} Job(s) aus Dictionary extrahiert")
elif isinstance(JOBS_RAW, list):
    JOBS = JOBS_RAW
else:
    log(f"FEHLER: jobs ist kein gültiges Format: {type(JOBS_RAW)}")
    JOBS = []

# Sicherstellen, dass JOBS eine Liste von Dictionaries ist
if not isinstance(JOBS, list):
    log(f"FEHLER: jobs konnte nicht zu Liste konvertiert werden: {type(JOBS)}")
    JOBS = []
elif JOBS and len(JOBS) > 0:
    # Prüfe den ersten Eintrag
    if isinstance(JOBS[0], str):
        log("WARNUNG: jobs scheint als Liste von Strings geladen zu sein. Versuche JSON-Parsing...")
        try:
            # Falls jobs als JSON-String gespeichert ist
            if JOBS[0].startswith('{'):
                JOBS = [json.loads(job) for job in JOBS]
            else:
                log(f"FEHLER: jobs ist nicht im erwarteten Format. Erster Eintrag: {JOBS[0]}")
                JOBS = []
        except Exception as e:
            log(f"FEHLER beim Parsen von jobs: {e}")
            JOBS = []
    # Filtere ungültige Einträge heraus
    valid_jobs = []
    for i, job in enumerate(JOBS):
        if isinstance(job, dict):
            valid_jobs.append(job)
        else:
            log(f"WARNUNG: Job {i} ist kein Dictionary: {type(job)} - {job}")
    JOBS = valid_jobs

log(f"Geladene Jobs: {len(JOBS)}")
if len(JOBS) == 0:
    log("WARNUNG: Keine gültigen Jobs gefunden!")

def weekday_today():
    return ["mo","di","mi","do","fr","sa","so"][datetime.today().weekday()]

def parse_date(date_str):
    """Parst verschiedene Datumsformate"""
    if not date_str:
        return None
    try:
        # ISO-Format: YYYY-MM-DD
        return date.fromisoformat(date_str)
    except ValueError:
        try:
            # Deutsches Format: DD.MM.YYYY
            parts = date_str.split('.')
            if len(parts) == 3:
                return date(int(parts[2]), int(parts[1]), int(parts[0]))
        except (ValueError, IndexError):
            pass
        try:
            # Format: DD-MM-YYYY
            parts = date_str.split('-')
            if len(parts) == 3 and len(parts[0]) <= 2:
                return date(int(parts[2]), int(parts[1]), int(parts[0]))
        except (ValueError, IndexError):
            pass
    return None

def in_date_range(job):
    if not isinstance(job, dict):
        return False
    date_start = job.get("date_start")
    date_end = job.get("date_end")
    if not date_start or not date_end:
        return True
    try:
        start = parse_date(date_start)
        end = parse_date(date_end)
        if start is None or end is None:
            log(f"WARNUNG: Konnte Datum nicht parsen: start={date_start}, end={date_end}")
            return True  # Wenn Datum nicht geparst werden kann, erlaube Aufnahme
        today = date.today()
        return start <= today <= end
    except Exception as e:
        log(f"FEHLER beim Prüfen des Datumsbereichs: {e}")
        return False

def in_weekday(job):
    if not isinstance(job, dict):
        return False
    if not job.get("weekdays"):
        return True
    weekdays = job.get("weekdays", [])
    if not isinstance(weekdays, list):
        return True
    return weekday_today() in weekdays

def now_str():
    return datetime.now().strftime("%H:%M")

def aufnehmen(job):
    if not isinstance(job, dict):
        log(f"FEHLER: aufnehmen() erhielt kein Dictionary: {type(job)}")
        return
    try:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        # Standard-Pfad zum NAS, falls nicht angegeben
        save_path_raw = job.get('save_path', DEFAULT_SAVE_PATH)
        # Konvertiere Windows-Pfade zu Linux-Pfaden
        save_path = save_path_raw.replace('\\', '/').replace('//', '/')
        # Entferne führende Slashes wenn es ein relativer Pfad ist
        if save_path.startswith('/') and save_path != DEFAULT_SAVE_PATH:
            # Falls es kein absoluter Pfad ist, verwende NAS Mount Point
            if NAS_MOUNT_POINT:
                save_path = os.path.join(NAS_MOUNT_POINT, save_path.lstrip('/'))
            else:
                save_path = os.path.join('/data', save_path.lstrip('/'))
        job_name = job.get('name', 'recording')
        fname = f"{save_path}/{job_name}_{ts}.mp3"
        
        log(f"Speicherpfad: {save_path}")
        log(f"Dateiname: {fname}")
        
        # Stelle sicher, dass das Verzeichnis existiert
        try:
            os.makedirs(save_path, exist_ok=True)
            log(f"Verzeichnis erstellt/überprüft: {save_path}")
            
            # Prüfe ob das Verzeichnis beschreibbar ist
            test_file = os.path.join(save_path, '.write_test')
            try:
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                log(f"Verzeichnis ist beschreibbar: {save_path}")
            except Exception as e:
                log(f"WARNUNG: Verzeichnis ist nicht beschreibbar: {e}")
        except Exception as e:
            log(f"FEHLER beim Erstellen des Verzeichnisses {save_path}: {e}")
            log(f"Versuche alternativen Pfad: /data")
            save_path = '/data'
            os.makedirs(save_path, exist_ok=True)
            fname = f"{save_path}/{job_name}_{ts}.mp3"
        
        log("=" * 50)
        log("Starte Aufnahme:", fname)
        log("=" * 50)
        
        stream_url = job.get("stream_url")
        if not stream_url:
            log("FEHLER: stream_url fehlt im Job")
            return
        
        time_start = job.get("time_start", "unbekannt")
        time_end = job.get("time_end")
        if not time_end:
            log("FEHLER: time_end fehlt im Job")
            return
        
        log(f"Stream URL: {stream_url}")
        log(f"Startzeit: {time_start}")
        log(f"Endzeit: {time_end}")
        log(f"Aktuelle Zeit: {now_str()}")
        
        log(f"Verbinde mit Stream: {stream_url}")
        response = requests.get(stream_url, stream=True, timeout=10)
        response.raise_for_status()
        log("Stream-Verbindung erfolgreich!")
        
        bytes_written = 0
        with open(fname, "wb") as f:
            max_iterations = 10000  # Sicherheitslimit (ca. 16 Minuten bei 0.1s sleep)
            iteration = 0
            chunk_iter = response.iter_content(chunk_size=8192)  # Größere Chunks für bessere Performance
            while now_str() != time_end and iteration < max_iterations:
                try:
                    data = next(chunk_iter, None)
                    if data:
                        f.write(data)
                        bytes_written += len(data)
                        if iteration % 100 == 0:  # Alle 100 Iterationen Status ausgeben
                            log(f"Fortschritt: {bytes_written / 1024 / 1024:.2f} MB geschrieben, Zeit: {now_str()}")
                    else:
                        # Keine Daten mehr verfügbar, warte kurz
                        time.sleep(0.1)
                    iteration += 1
                except StopIteration:
                    # Stream ist zu Ende, aber wir warten weiter bis time_end
                    time.sleep(0.1)
                    iteration += 1
                except Exception as e:
                    log(f"FEHLER beim Lesen des Streams: {e}")
                    break
        
        if iteration >= max_iterations:
            log("WARNUNG: Maximale Iterationen erreicht, Aufnahme gestoppt")
        
        response.close()
        
        # Prüfe ob die Datei existiert und ihre Größe
        if os.path.exists(fname):
            file_size = os.path.getsize(fname)
            log("=" * 50)
            log(f"Aufnahme erfolgreich beendet!")
            log(f"Datei: {fname}")
            log(f"Größe: {file_size / 1024 / 1024:.2f} MB")
            log("=" * 50)
        else:
            log(f"FEHLER: Datei wurde nicht erstellt: {fname}")
    except requests.exceptions.RequestException as e:
        log(f"FEHLER beim Verbinden mit dem Stream: {e}")
    except Exception as e:
        log(f"FEHLER bei der Aufnahme: {e}")
        import traceback
        traceback.print_exc()

try:
    log(f"\n{'='*50}")
    log(f"Starte Hauptschleife mit {len(JOBS)} Job(s)")
    log(f"{'='*50}")
    
    # Zeige alle konfigurierten Jobs an
    if len(JOBS) > 0:
        log("\nKonfigurierte Jobs:")
        for i, job in enumerate(JOBS):
            if isinstance(job, dict):
                job_name = job.get('name', f'Job {i}')
                time_start = job.get("time_start", "nicht gesetzt")
                time_end = job.get("time_end", "nicht gesetzt")
                weekdays = job.get("weekdays", [])
                log(f"  Job {i+1}: {job_name}")
                log(f"    Startzeit: {time_start}")
                log(f"    Endzeit: {time_end}")
                log(f"    Wochentage: {weekdays if weekdays else 'alle'}")
    else:
        log("WARNUNG: Keine Jobs konfiguriert!")
        log("Bitte Jobs in der Add-on-Konfiguration hinzufügen.")
    
    log(f"\nAktuelle Zeit: {now_str()}")
    log(f"Aktueller Wochentag: {weekday_today()}")
    log(f"Prüfe alle 5 Sekunden auf Startzeiten...")
    log(f"{'='*50}\n")
    
    last_log_time = ""
    check_count = 0
    
    while True:
        try:
            uhr = now_str()
            check_count += 1
            
            # Zeige Status alle Minute
            if uhr != last_log_time:
                last_log_time = uhr
                log(f"[{uhr}] Prüfe Jobs... (Prüfung #{check_count})")
            
            # Prüfe jeden Job
            for i, job in enumerate(JOBS):
                # Sicherstellen, dass job ein Dictionary ist
                if not isinstance(job, dict):
                    continue
                
                job_name = job.get('name', f'Job {i}')
                time_start = job.get("time_start")
                
                # Prüfe ob Startzeit erreicht wurde
                if time_start and uhr == time_start:
                    log(f"\n{'='*50}")
                    log(f">>> ZEITPUNKT ERREICHT! <<<")
                    log(f"Job: {job_name}")
                    log(f"Startzeit: {time_start}")
                    log(f"Aktuelle Zeit: {uhr}")
                    log(f"{'='*50}")
                    
                    # Prüfe Bedingungen
                    date_ok = in_date_range(job)
                    weekday_ok = in_weekday(job)
                    
                    log(f"Datumsbereich OK: {date_ok}")
                    log(f"Wochentag OK: {weekday_ok}")
                    
                    if date_ok and weekday_ok:
                        log(f">>> STARTE AUFNAHME: {job_name}")
                        log(f"{'='*50}\n")
                        aufnehmen(job)
                        log(f"\n{'='*50}")
                        log(f"Aufnahme beendet für Job: {job_name}")
                        log(f"{'='*50}\n")
                    else:
                        log(f">>> Job übersprungen (Bedingungen nicht erfüllt)")
                        log(f"{'='*50}\n")
            
            # Prüfe häufiger (alle 5 Sekunden statt 20)
            # So wird die Startzeit nicht verpasst
            time.sleep(5)
            
        except KeyboardInterrupt:
            log("\nProgramm durch Benutzer beendet")
            break
        except Exception as e:
            log(f"FEHLER in der Hauptschleife: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)  # Warte bei Fehlern
except Exception as e:
    log(f"KRITISCHER FEHLER: {e}")
    import traceback
    traceback.print_exc()