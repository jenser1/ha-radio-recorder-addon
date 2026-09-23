"""Zeitgesteuerte Aufnahmen auf Basis von APScheduler.

Die Zeitzone wird ausdruecklich gesetzt. Ohne sie liefe der Scheduler in der
Zeitzone des Containers (UTC) und alle Zeitplaene waeren gegenueber der
Home-Assistant-Anzeige verschoben.
"""

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config, db
from .recorder import recorder

# Reihenfolge und Beschriftung der Wochentage in der Oberflaeche.
WEEKDAYS = [
    ("mon", "Mo"), ("tue", "Di"), ("wed", "Mi"), ("thu", "Do"),
    ("fri", "Fr"), ("sat", "Sa"), ("sun", "So"),
]
WEEKDAY_KEYS = [key for key, _ in WEEKDAYS]
WEEKDAY_LABELS = dict(WEEKDAYS)

_scheduler = None


def resolve_timezone():
    """Ermittelt die Zeitzone aus der Umgebung, mit Rueckfallebene."""
    name = config.TIMEZONE
    if not name:
        print("[scheduler] Keine Zeitzone gesetzt - verwende die des Systems. "
              "Zeitplaene koennen dadurch verschoben sein.", flush=True)
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception as err:
        print(f"[scheduler] Zeitzone {name!r} unbekannt ({err}) - "
              f"verwende die des Systems.", flush=True)
        return None


def parse_start_time(value):
    """Prueft eine Uhrzeit im Format HH:MM und liefert (Stunde, Minute)."""
    try:
        parsed = datetime.strptime((value or "").strip(), "%H:%M")
    except ValueError:
        raise ValueError(f"Ungueltige Startzeit: {value!r} (erwartet HH:MM)") from None
    return parsed.hour, parsed.minute


def validate_weekdays(values):
    """Filtert auf bekannte Wochentage und behaelt die Wochenreihenfolge bei."""
    chosen = {v.strip().lower() for v in (values or [])}
    valid = [key for key in WEEKDAY_KEYS if key in chosen]
    if not valid:
        raise ValueError("Bitte mindestens einen Wochentag auswaehlen.")
    return valid


def start():
    """Startet den Scheduler und traegt alle aktiven Zeitplaene ein."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    timezone = resolve_timezone()
    _scheduler = BackgroundScheduler(
        timezone=timezone,
        job_defaults={
            "coalesce": True,          # nachgeholte Starts nur einmal ausfuehren
            "misfire_grace_time": 300, # bis 5 Minuten Verspaetung sind ok
            "max_instances": 1,
        },
    )
    _scheduler.start()
    if timezone is not None:
        print(f"[scheduler] Zeitzone: {timezone}", flush=True)

    sync_all()
    return _scheduler


def shutdown():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None


def sync_all():
    """Gleicht die eingetragenen Zeitplaene mit der Datenbank ab."""
    if _scheduler is None:
        return 0
    count = 0
    for job in db.list_jobs():
        if job["enabled"]:
            try:
                schedule(job)
                count += 1
            except Exception as err:
                print(f"[scheduler] Zeitplan {job['name']!r} nicht eintragbar: "
                      f"{err}", flush=True)
        else:
            unschedule(job["id"])
    print(f"[scheduler] {count} Zeitplan/-plaene aktiv", flush=True)
    return count


def schedule(job):
    """Traegt einen einzelnen Zeitplan ein bzw. aktualisiert ihn."""
    if _scheduler is None:
        return
    hour, minute = parse_start_time(job["start_time"])
    weekdays = validate_weekdays(job["weekdays"])
    _scheduler.add_job(
        func=_fire,
        args=[job["id"]],
        trigger=CronTrigger(day_of_week=",".join(weekdays),
                            hour=hour, minute=minute),
        id=job["id"],
        name=job["name"],
        replace_existing=True,
    )


def unschedule(job_id):
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass


def next_runs():
    """Naechste Ausfuehrung je Zeitplan, fuer die Anzeige."""
    if _scheduler is None:
        return {}
    result = {}
    for job in _scheduler.get_jobs():
        result[job.id] = getattr(job, "next_run_time", None)
    return result


def _fire(job_id):
    """Wird vom Scheduler aufgerufen, wenn ein Zeitplan faellig ist."""
    job = db.get_job(job_id)
    if job is None:
        print(f"[scheduler] Zeitplan {job_id} existiert nicht mehr", flush=True)
        unschedule(job_id)
        return
    if not job["enabled"]:
        return

    # Laeuft fuer diesen Zeitplan schon eine Aufnahme, wird nicht doppelt
    # gestartet - etwa wenn sich Dauer und naechster Start ueberschneiden.
    for running in recorder.active():
        current = db.get_recording(running["id"])
        if current and current.get("job_id") == job_id:
            print(f"[scheduler] {job['name']!r} laeuft bereits - "
                  f"Start uebersprungen", flush=True)
            return

    try:
        recorder.start(
            station_key=job["station"],
            duration_minutes=job["duration_minutes"],
            label=job["name"],
            job_id=job_id,
        )
    except Exception as err:
        print(f"[scheduler] Start von {job['name']!r} fehlgeschlagen: {err}",
              flush=True)
