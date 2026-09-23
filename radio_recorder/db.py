"""SQLite-Datenhaltung fuer Zeitplaene und Aufnahmen.

Loest die frueheren ``jobs.json``-Dateien ab. Bestehende Zeitplaene werden
beim ersten Start automatisch uebernommen.
"""

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA_VERSION = 1

_init_lock = threading.Lock()
_initialised = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,
    name             TEXT    NOT NULL,
    station          TEXT    NOT NULL,
    start_time       TEXT    NOT NULL,   -- HH:MM
    duration_minutes INTEGER NOT NULL,
    weekdays         TEXT    NOT NULL,   -- z.B. "mon,tue,fri"
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS recordings (
    id            TEXT PRIMARY KEY,
    job_id        TEXT,                  -- NULL bei manueller Aufnahme
    label         TEXT    NOT NULL DEFAULT '',
    station_key   TEXT    NOT NULL,
    station_name  TEXT    NOT NULL,
    stream_url    TEXT    NOT NULL,
    ext           TEXT    NOT NULL DEFAULT 'mp3',
    state         TEXT    NOT NULL,      -- running|completed|failed|cancelled
    started_at    TEXT    NOT NULL,
    planned_end   TEXT    NOT NULL,
    ended_at      TEXT,
    work_dir      TEXT,
    output_file   TEXT,
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    resume_count  INTEGER NOT NULL DEFAULT 0,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_recordings_state   ON recordings(state);
CREATE INDEX IF NOT EXISTS idx_recordings_started ON recordings(started_at DESC);
"""

# Spalten, die ueber update_recording() geschrieben werden duerfen.
_RECORDING_FIELDS = {
    "state", "ended_at", "output_file", "size_bytes",
    "resume_count", "retry_count", "error", "work_dir", "planned_end",
}


@contextmanager
def connect():
    """Eine Verbindung pro Vorgang - SQLite regelt den Rest ueber WAL."""
    conn = sqlite3.connect(str(config.DB_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    """Legt die Datenbank an und uebernimmt alte Zeitplaene. Idempotent."""
    global _initialised
    with _init_lock:
        if _initialised:
            return
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        _import_legacy_jobs()
        _initialised = True


def _import_legacy_jobs():
    """Uebernimmt ``/data/jobs.json`` der Version 0.2.0 einmalig."""
    path = config.LEGACY_JOBS_FILE
    if not path.exists():
        return
    try:
        legacy = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        print(f"[db] jobs.json konnte nicht gelesen werden: {err}", flush=True)
        return
    if not isinstance(legacy, list):
        legacy = []

    imported = 0
    for entry in legacy:
        if not isinstance(entry, dict):
            continue
        try:
            add_job(
                name=entry.get("name") or "Uebernommen",
                station=entry.get("station") or "sunshine_live",
                start_time=entry["start_time"],
                duration_minutes=int(entry.get("duration_minutes", 0)),
                weekdays=entry.get("weekdays") or [],
                enabled=bool(entry.get("enabled", True)),
                job_id=entry.get("id"),
            )
            imported += 1
        except Exception as err:
            print(f"[db] Zeitplan uebersprungen ({entry!r}): {err}", flush=True)

    try:
        path.replace(path.with_name("jobs.json.uebernommen"))
    except Exception:
        pass
    print(f"[db] {imported} Zeitplan/-plaene aus jobs.json uebernommen", flush=True)


# --- Zeitplaene ----------------------------------------------------------

def list_jobs():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY start_time, name").fetchall()
    return [_job_from_row(r) for r in rows]


def get_job(job_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job_from_row(row) if row else None


def add_job(name, station, start_time, duration_minutes, weekdays,
            enabled=True, job_id=None):
    job_id = job_id or "job_" + uuid.uuid4().hex[:10]
    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO jobs
               (id, name, station, start_time, duration_minutes, weekdays,
                enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, name, station, start_time, int(duration_minutes),
             ",".join(weekdays), 1 if enabled else 0,
             datetime.now().isoformat(timespec="seconds")),
        )
    return job_id


def delete_job(job_id):
    with connect() as conn:
        cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cur.rowcount > 0


def set_job_enabled(job_id, enabled):
    with connect() as conn:
        conn.execute("UPDATE jobs SET enabled = ? WHERE id = ?",
                     (1 if enabled else 0, job_id))


def _job_from_row(row):
    job = dict(row)
    job["weekdays"] = [d for d in (job.get("weekdays") or "").split(",") if d]
    job["enabled"] = bool(job["enabled"])
    return job


# --- Aufnahmen -----------------------------------------------------------

def create_recording(recording_id, station_key, station_name, stream_url, ext,
                     started_at, planned_end, work_dir, label="", job_id=None):
    with connect() as conn:
        conn.execute(
            """INSERT INTO recordings
               (id, job_id, label, station_key, station_name, stream_url, ext,
                state, started_at, planned_end, work_dir)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)""",
            (recording_id, job_id, label, station_key, station_name, stream_url,
             ext, started_at, planned_end, work_dir),
        )


def update_recording(recording_id, **fields):
    unknown = set(fields) - _RECORDING_FIELDS
    if unknown:
        raise ValueError(f"Unbekannte Felder: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connect() as conn:
        conn.execute(
            f"UPDATE recordings SET {assignments} WHERE id = ?",
            (*fields.values(), recording_id),
        )


def get_recording(recording_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM recordings WHERE id = ?",
                           (recording_id,)).fetchone()
    return dict(row) if row else None


def list_recordings(states=None, limit=50):
    query = "SELECT * FROM recordings"
    params = []
    if states:
        placeholders = ",".join("?" for _ in states)
        query += f" WHERE state IN ({placeholders})"
        params.extend(states)
    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(int(limit))
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def list_running():
    """Aufnahmen, die laut Datenbank noch laufen - auch nach einem Neustart."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM recordings WHERE state = 'running' ORDER BY started_at"
        ).fetchall()
    return [dict(r) for r in rows]
