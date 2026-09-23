import json
from datetime import datetime, date
import requests
import time
import os
import sys

# Konfigurieren Sie die Ausgabe so, dass sie sofort im Log erscheint
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def log(*args, **kwargs):
    """Log-Funktion die sofort ausgegeben wird"""
    message = ' '.join(str(arg) for arg in args) if args else ''
    print(message, **kwargs, flush=True)

# --- Hilfsfunktionen ---

def weekday_today():
    """Gibt den aktuellen Wochentag im Format [mo, di, mi, do, fr, sa, so] zurück"""
    return ["mo","di","mi","do","fr","sa","so"][datetime.today().weekday()]

def now_str():
    """Gibt die aktuelle Uhrzeit als H:M-String zurück (z.B. '10:00')"""
    return datetime.now().strftime("%H:%M")

def parse_date(date_str):
    """Parst das Datum im Format YYYY-MM-DD"""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None

def in_date_range(job):
    """Prüft, ob das heutige Datum im definierten Bereich liegt."""
    date_start = job.get("date_start")
    date_end = job.get("date_end")
    if not date_start or not date_end:
        return True
    
    start = parse_date(date_start)
    end = parse_date(date_end)
    today = date.today()
    
    # Standardmäßig aufnehmen, wenn Daten fehlerhaft sind
    if start is None or end is None:
        return True 

    return start <= today <= end

def in_weekday(job):
    """Prüft, ob der heutige Wochentag in der Job-Definition enthalten ist."""
    weekdays = job.get("weekdays")
    if not weekdays:
        return True
    if not isinstance(weekdays, list):
        return True
    return weekday_today() in weekdays

# --- Hauptlogik: Aufnahme ---

def aufnehmen(job):
    """Startet die Aufnahme des Streams und stoppt zur time_end."""
    try:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        
        # Standard-Speicherpfad verwenden
        DEFAULT_SAVE_PATH = '/data/recordings' 
        
        job_name = job.get('name', 'recording').replace(" ", "_")
        save_path = job.get('save_path', DEFAULT_SAVE_PATH).replace('\\', '/')
        os.makedirs(save_path, exist_ok=True)
        
        fname = f"{save_path}/{job_name}_{ts}.mp3"
        stream_url = job.get("stream_url")
        time_end = job.get("time_end")
        
        if not stream_url or not time_end:
            log(f"FEHLER: Stream URL ({stream_url}) oder Endzeit ({time_end}) fehlt.")
            return

        log("=" * 50)
        log(f"Starte Aufnahme: {job_name} ({now_str()} bis {time_end})")
        log(f"Speicherziel: {fname}")
        log("=" * 50)
        
        # Verbindung mit dem Stream herstellen
        response = requests.get(stream_url, stream=True, timeout=15)
        response.raise_for_status()
        log("Stream-Verbindung erfolgreich hergestellt.")
        
        bytes_written = 0
        
        # Aufnahme-Loop: Läuft, bis die aktuelle Uhrzeit der time_end entspricht
        with open(fname, "wb") as f:
            chunk_iter = response.iter_content(chunk_size=8192)
            # Zähler für das Protokollieren (ca. alle 800 KB)
            chunk_counter = 0 
            while now_str() != time_end:
                try:
                    data = next(chunk_iter, None)
                    if data:
                        f.write(data)
                        bytes_written += len(data)
                        
                        chunk_counter += 1
                        if chunk_counter % 100 == 0: 
                            log(f"Fortschritt: {bytes_written / 1024 / 1024:.2f} MB geschrieben, Zeit: {now_str()}")
                        
                    else:
                        # Warte kurz, wenn keine Daten verfügbar sind
                        time.sleep(0.1)
                except StopIteration:
                    # Stream unerwartet beendet, warte kurz, bevor wir es erneut versuchen
                    time.sleep(1)
                except Exception as e:
                    log(f"FEHLER beim Schreiben: {e}. Stoppe Aufnahme.")
                    break
        
        response.close()
        
        file_size = os.path.getsize(fname) if os.path.exists(fname) else 0
        log("=" * 50)
        log(f"Aufnahme beendet (Zeitpunkt {time_end} erreicht).")
        log(f"Dateigröße: {file_size / 1024 / 1024:.2f} MB")
        log("=" * 50)

    except requests.exceptions.RequestException as e:
        log(f"FEHLER beim Verbinden mit dem Stream: {e}")
    except Exception as e:
        log(f"KRITISCHER FEHLER bei der Aufnahme: {e}")
        import traceback
        traceback.print_exc()

# --- Initialisierung und Hauptschleife ---

log("=" * 50)
log("Radio Recorder gestartet (Minimalversion)")
log("=" * 50)

# Konfiguration laden
try:
    with open("/data/options.json") as f:
        cfg = json.load(f)
    JOBS = cfg.get("jobs", [])
    if not isinstance(JOBS, list):
        log("WARNUNG: 'jobs' ist nicht als Liste konfiguriert. Verwende leere Liste.")
        JOBS = []
except Exception as e:
    log(f"FEHLER beim Laden der Konfiguration (/data/options.json): {e}")
    JOBS = []

log(f"Geladene Jobs: {len(JOBS)}")

# Detaillierte Job-Protokollierung, um Konfigurationsprobleme zu identifizieren
if JOBS:
    log("\nDetaillierte Job-Konfiguration:")
    for i, job in enumerate(JOBS):
        # Sicherstellen, dass Job ein Dictionary ist, bevor auf Keys zugegriffen wird
        if not isinstance(job, dict):
            log(f"--- JOB {i+1}: UNGÜLTIG (Kein Dictionary) ---")
            continue

        job_name = job.get('name', f'Unbenannter Job {i+1}')
        log(f"--- JOB {i+1}: {job_name} ---")
        log(f"  Stream URL: {job.get('stream_url', 'FEHLT')}")
        log(f"  Startzeit: {job.get('time_start', 'FEHLT')}")
        log(f"  Endzeit: {job.get('time_end', 'FEHLT')}")
        log(f"  Speicherpfad: {job.get('save_path', '/data/recordings')}")
        
        weekdays = job.get('weekdays', 'Alle')
        date_start = job.get('date_start', 'n/a')
        date_end = job.get('date_end', 'n/a')
        
        log(f"  Wochentage: {weekdays if weekdays else 'Alle'}")
        log(f"  Datumsbereich: {date_start} bis {date_end}")
        
        # Bedingungen für heute prüfen
        log(f"  PRÜFUNG HEUTE (Wochentag {weekday_today()}):")
        log(f"    Wochentag OK: {in_weekday(job)}")
        log(f"    Datumsbereich OK: {in_date_range(job)}")

    log("-------------------------------------------\n")
else:
    log("ACHTUNG: Es wurden keine gültigen Jobs in der Konfiguration gefunden.")
    log("Bitte überprüfen Sie die 'jobs'-Liste in /data/options.json.")


log(f"Aktuelle Zeit: {now_str()}, Wochentag: {weekday_today()}")
log(f"Prüfe alle 5 Sekunden auf Startzeiten...\n")

# Hauptschleife
last_log_time = ""

while True:
    try:
        uhr = now_str()
        
        # Zeige Status alle Minute
        if uhr != last_log_time:
            last_log_time = uhr
            log(f"[{uhr}] Prüfe Jobs...")
        
        # Prüfe jeden Job
        for i, job in enumerate(JOBS):
            if not isinstance(job, dict):
                continue
            
            job_name = job.get('name', f'Job {i}')
            time_start = job.get("time_start")
            
            # Prüfe ob Startzeit erreicht wurde
            if time_start and uhr == time_start:
                
                # Bedingungsprüfung
                date_ok = in_date_range(job)
                weekday_ok = in_weekday(job)
                
                if date_ok and weekday_ok:
                    log(f">>> STARTZEIT ERREICHT! Starte Aufnahme für Job: {job_name}")
                    aufnehmen(job)
                else:
                    log(f">>> STARTZEIT ERREICHT, aber Bedingungen für Job '{job_name}' nicht erfüllt (Datum/Wochentag).")
            
        # Prüfe alle 5 Sekunden, um die Startminute nicht zu verpassen
        time.sleep(5)
            
    except KeyboardInterrupt:
        log("\nProgramm durch Benutzer beendet")
        break
    except Exception as e:
        log(f"FEHLER in der Hauptschleife: {e}")
        time.sleep(10)