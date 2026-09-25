"""Aufnahme-Steuerung auf Basis von ffmpeg.

Eine Aufnahme wird nicht in eine einzelne Datei geschrieben, sondern in
kurze Segmente im Arbeitsverzeichnis. Das hat zwei Gruende:

* Stuerzt das Add-on ab oder wird es aktualisiert, ist hoechstens das
  angefangene Segment verloren - alles davor bleibt erhalten.
* Nach einem Neustart kann die Aufnahme fortgesetzt werden, indem einfach
  weitergezaehlt wird. Am Ende werden alle Segmente verlustfrei zu einer
  Datei zusammengefuegt.

Massgeblich ist dabei immer die geplante *Endzeit*, nicht die verbleibende
Dauer. Dadurch endet eine Aufnahme auch dann zur richtigen Uhrzeit, wenn
das Add-on zwischendurch ein paar Minuten weg war.
"""

import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from . import config, db, probe

# ffmpeg beendet sich nach SIGINT mit 255 - das ist kein Fehler.
_SIGINT_EXIT_CODES = (0, 255)

# Wie lange nach der geplanten Endzeit gewartet wird, bevor hart gestoppt
# wird. Noetig, falls der Stream stockt und ffmpegs eigenes -t nicht greift.
_END_GRACE_SECONDS = 60

# Das Segmentformat je Dateiendung steht in probe.CODEC_MAP.

# Kein Rueckgabewert von ffmpeg, sondern unser Kennzeichen dafuer, dass sich
# das Programm gar nicht erst starten liess. Wiederholen waere hier zwecklos.
_FFMPEG_MISSING = -1001

_PROCESS_STOP_SIGNAL = signal.SIGINT if os.name != "nt" else signal.SIGTERM


def safe_filename(text):
    """Macht aus beliebigem Text einen unbedenklichen Dateinamen."""
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", (text or "").strip())
    return text.strip("_")


class _Active:
    """Laufzeitzustand einer Aufnahme - nur im Speicher."""

    def __init__(self, recording_id, record):
        self.id = recording_id
        self.record = record
        self.proc = None
        self.stop_requested = False
        self.paused = False          # Herunterfahren: Zustand bleibt "running"
        self.notice = None           # Grund, falls von selbst gestoppt wurde
        self.thread = None
        self.stderr_tail = deque(maxlen=40)
        self.lock = threading.Lock()


class Recorder:
    """Verwaltet alle laufenden Aufnahmen."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = {}
        self._shutting_down = False

    # --- oeffentliche Schnittstelle -------------------------------------

    def start(self, station_key, duration_minutes, label="", job_id=None):
        """Startet eine neue Aufnahme und liefert deren Kennung."""
        station = db.get_station(station_key)
        if station is None:
            raise ValueError(f"Unbekannter Sender: {station_key!r}")
        duration = int(duration_minutes)
        if duration < 1 or duration > config.MAX_DURATION_MINUTES:
            raise ValueError(
                f"Dauer muss zwischen 1 Minute und "
                f"{config.MAX_DURATION_MINUTES // 60} Stunden liegen."
            )

        check_disk_space(station, duration)

        started = datetime.now()
        planned_end = started + timedelta(minutes=duration)
        rid = uuid.uuid4().hex[:8]
        work_dir = config.WORK_DIR / rid
        work_dir.mkdir(parents=True, exist_ok=True)

        db.create_recording(
            recording_id=rid,
            job_id=job_id,
            label=label or "",
            station_key=station_key,
            station_name=station["name"],
            stream_url=station["url"],
            ext=station.get("ext", "mp3"),
            started_at=started.isoformat(timespec="seconds"),
            planned_end=planned_end.isoformat(timespec="seconds"),
            work_dir=str(work_dir),
        )

        record = db.get_recording(rid)
        self._launch(rid, record)
        print(f"[rec {rid}] Aufnahme gestartet: {station['name']}, "
              f"Ende {planned_end:%H:%M:%S}", flush=True)
        return rid

    def stop(self, recording_id):
        """Beendet eine Aufnahme vorzeitig auf Wunsch des Benutzers."""
        with self._lock:
            active = self._active.get(recording_id)
        if not active:
            return False
        active.stop_requested = True
        self._signal_process(active)
        return True

    def resume_pending(self):
        """Nimmt nach einem Neustart alle offenen Aufnahmen wieder auf."""
        pending = db.list_running()
        if not pending:
            return 0

        resumed = 0
        for record in pending:
            rid = record["id"]
            try:
                planned_end = datetime.fromisoformat(record["planned_end"])
            except (TypeError, ValueError):
                planned_end = datetime.now()

            work_dir = Path(record["work_dir"] or (config.WORK_DIR / rid))
            work_dir.mkdir(parents=True, exist_ok=True)

            if datetime.now() >= planned_end:
                # Endzeit lag im Ausfallzeitraum - direkt abschliessen.
                print(f"[rec {rid}] Endzeit bereits erreicht, schliesse ab",
                      flush=True)
                self._finalize(rid, record)
                continue

            db.update_recording(rid, resume_count=record["resume_count"] + 1)
            record = db.get_recording(rid)
            self._launch(rid, record)
            resumed += 1
            print(f"[rec {rid}] Aufnahme fortgesetzt "
                  f"(Versuch {record['resume_count'] + 1}), "
                  f"Ende {planned_end:%H:%M:%S}", flush=True)
        return resumed

    def shutdown(self, timeout=None):
        """Haelt alle Aufnahmen an, ohne sie abzuschliessen.

        Der Datenbankzustand bleibt auf ``running``, damit der naechste Start
        genau dort weitermacht.
        """
        timeout = config.SHUTDOWN_TIMEOUT if timeout is None else timeout
        self._shutting_down = True
        with self._lock:
            actives = list(self._active.values())
        if not actives:
            return

        print(f"[rec] Halte {len(actives)} laufende Aufnahme(n) an ...",
              flush=True)
        for active in actives:
            active.paused = True
            self._signal_process(active)

        deadline = time.monotonic() + timeout
        for active in actives:
            remaining = max(0.5, deadline - time.monotonic())
            if active.thread:
                active.thread.join(timeout=remaining)

    def active(self):
        """Momentaufnahme aller laufenden Aufnahmen fuer die Oberflaeche."""
        now = datetime.now()
        result = []
        with self._lock:
            actives = list(self._active.items())

        for rid, active in actives:
            record = active.record
            try:
                started = datetime.fromisoformat(record["started_at"])
                planned_end = datetime.fromisoformat(record["planned_end"])
            except (TypeError, ValueError):
                continue
            result.append({
                "id": rid,
                "station_name": record["station_name"],
                "label": record["label"],
                "started_at": started,
                "planned_end": planned_end,
                "elapsed": _format_span((now - started).total_seconds()),
                "remaining": _format_span((planned_end - now).total_seconds()),
                "size_bytes": _work_dir_size(Path(record["work_dir"])),
                "resume_count": record["resume_count"],
                "retry_count": record["retry_count"],
            })
        result.sort(key=lambda item: item["started_at"])
        return result

    def is_active(self, recording_id):
        with self._lock:
            return recording_id in self._active

    # --- innere Abläufe --------------------------------------------------

    def _launch(self, recording_id, record):
        active = _Active(recording_id, record)
        with self._lock:
            self._active[recording_id] = active
        active.thread = threading.Thread(
            target=self._run, args=(active,),
            name=f"recording-{recording_id}", daemon=True,
        )
        active.thread.start()

    def _run(self, active):
        """Haelt die Aufnahme bis zur geplanten Endzeit am Leben."""
        rid = active.id
        record = active.record
        work_dir = Path(record["work_dir"])
        ext = record["ext"]
        planned_end = datetime.fromisoformat(record["planned_end"])
        retries = record["retry_count"]
        failure = None

        try:
            while True:
                remaining = (planned_end - datetime.now()).total_seconds()
                if remaining <= 1:
                    break
                if active.stop_requested or active.paused:
                    break

                returncode = self._run_ffmpeg(active, work_dir, ext, remaining)

                if active.stop_requested or active.paused or self._shutting_down:
                    break
                if returncode == _FFMPEG_MISSING:
                    # Einrichtungsfehler - ein weiterer Versuch aendert nichts.
                    failure = _last_error_line(active.stderr_tail)
                    print(f"[rec {rid}] {failure}", flush=True)
                    break
                if (planned_end - datetime.now()).total_seconds() <= 5:
                    break   # regulaeres Ende

                # ffmpeg ist vor der Zeit ausgestiegen: Stream weg oder Fehler.
                retries += 1
                db.update_recording(rid, retry_count=retries)
                detail = _last_error_line(active.stderr_tail)
                if retries > config.MAX_STREAM_RETRIES:
                    failure = (f"Stream nach {config.MAX_STREAM_RETRIES} "
                               f"Versuchen nicht erreichbar. {detail}").strip()
                    print(f"[rec {rid}] {failure}", flush=True)
                    break

                print(f"[rec {rid}] Stream abgebrochen (Code {returncode}), "
                      f"neuer Versuch {retries}/{config.MAX_STREAM_RETRIES} "
                      f"in {config.RETRY_BACKOFF_SECONDS}s. {detail}", flush=True)
                if self._sleep_interruptible(active, config.RETRY_BACKOFF_SECONDS):
                    break
        except Exception as err:                      # pragma: no cover
            failure = f"Unerwarteter Fehler: {err}"
            print(f"[rec {rid}] {failure}", flush=True)
        finally:
            with self._lock:
                self._active.pop(rid, None)
            if active.paused or self._shutting_down:
                # Zustand bleibt "running" - der naechste Start macht weiter.
                print(f"[rec {rid}] angehalten, wird beim naechsten Start "
                      f"fortgesetzt", flush=True)
            else:
                self._finalize(rid, db.get_recording(rid) or record,
                               cancelled=active.stop_requested,
                               failure=failure or active.notice)

    def _run_ffmpeg(self, active, work_dir, ext, remaining_seconds):
        """Startet ffmpeg fuer einen Abschnitt und wartet auf das Ende."""
        record = active.record
        start_number = _next_segment_number(work_dir, ext)
        pattern = str(work_dir / f"seg_%05d.{ext}")

        cmd = [
            *config.FFMPEG,
            "-hide_banner",
            "-loglevel", "warning",
            "-nostdin",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "10",
            "-reconnect_on_network_error", "1",
            "-reconnect_on_http_error", "4xx,5xx",
            "-i", record["stream_url"],
            "-vn",
            "-c:a", "copy",
            "-t", str(int(remaining_seconds)),
            "-f", "segment",
            "-segment_format", probe.segment_format_for(ext),
            "-segment_time", str(config.SEGMENT_MINUTES * 60),
            "-segment_start_number", str(start_number),
            "-reset_timestamps", "1",
            "-y", pattern,
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
            )
        except (FileNotFoundError, PermissionError, OSError) as err:
            active.stderr_tail.append(
                f"ffmpeg konnte nicht gestartet werden ({err}). "
                f"Ist es im Image installiert?")
            return _FFMPEG_MISSING

        with active.lock:
            active.proc = proc

        reader = threading.Thread(
            target=_drain_stderr, args=(proc, active.stderr_tail), daemon=True)
        reader.start()

        hard_stop = datetime.fromisoformat(record["planned_end"]) + timedelta(
            seconds=_END_GRACE_SECONDS)
        naechste_platzpruefung = time.monotonic() + config.SPACE_CHECK_SECONDS
        signalled = False

        while proc.poll() is None:
            if not signalled and datetime.now() >= hard_stop:
                # Stream stockt: ffmpegs -t zaehlt Stream-Zeit, nicht Uhrzeit.
                print(f"[rec {active.id}] Endzeit ueberschritten, stoppe",
                      flush=True)
                active.stop_requested = True
                self._signal_process(active)
                signalled = True

            # Bei langen Aufnahmen kann der Platz waehrenddessen ausgehen.
            # Dann lieber geordnet stoppen und das Aufgenommene behalten,
            # als ffmpeg mitten im Schreiben scheitern zu lassen.
            if not signalled and time.monotonic() >= naechste_platzpruefung:
                naechste_platzpruefung = (time.monotonic()
                                          + config.SPACE_CHECK_SECONDS)
                frei = free_bytes(work_dir)
                if frei is not None and frei < config.MIN_FREE_MB * 1024 * 1024:
                    active.notice = (
                        f"Aufnahme vorzeitig beendet: nur noch {_mb(frei)} "
                        f"frei im Arbeitsordner. Das bis dahin Aufgenommene "
                        f"wurde gespeichert.")
                    print(f"[rec {active.id}] {active.notice}", flush=True)
                    active.stop_requested = True
                    self._signal_process(active)
                    signalled = True

            time.sleep(0.5)

        reader.join(timeout=5)
        with active.lock:
            active.proc = None
        return proc.returncode

    def _signal_process(self, active):
        """Bittet ffmpeg, die laufende Datei sauber zu schliessen."""
        with active.lock:
            proc = active.proc
        if not proc or proc.poll() is not None:
            return
        try:
            proc.send_signal(_PROCESS_STOP_SIGNAL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _sleep_interruptible(self, active, seconds):
        """Wartet, bricht aber ab, wenn gestoppt wird. True = abgebrochen."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if active.stop_requested or active.paused or self._shutting_down:
                return True
            time.sleep(0.5)
        return False

    def _finalize(self, recording_id, record, cancelled=False, failure=None):
        """Fuegt die Segmente zusammen und schreibt das Ergebnis fort."""
        rid = recording_id
        work_dir = Path(record["work_dir"] or (config.WORK_DIR / rid))
        ext = record["ext"]
        ended_at = datetime.now().isoformat(timespec="seconds")
        segments = _segments(work_dir, ext)
        recorded_bytes = sum(seg.stat().st_size for seg in segments)

        if not segments or recorded_bytes == 0:
            message = failure or "Es wurden keine Daten aufgezeichnet."
            db.update_recording(rid, state="failed", ended_at=ended_at,
                                error=message, size_bytes=0)
            _remove_dir(work_dir)
            print(f"[rec {rid}] FEHLGESCHLAGEN: {message}", flush=True)
            return

        target = _output_path(record)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _join_segments(segments, target, ext)
        except Exception as err:
            message = (f"Zusammenfuegen fehlgeschlagen: {err}. "
                       f"Die Segmente bleiben unter {work_dir} erhalten.")
            db.update_recording(rid, state="failed", ended_at=ended_at,
                                error=message, size_bytes=recorded_bytes)
            print(f"[rec {rid}] {message}", flush=True)
            return

        size = target.stat().st_size if target.exists() else 0
        state = "cancelled" if cancelled else "completed"
        # Ein abgebrochener Stream mit brauchbarem Teilergebnis wird nicht als
        # Fehler gewertet, der Hinweis bleibt aber erhalten.
        db.update_recording(rid, state=state, ended_at=ended_at,
                            output_file=str(target), size_bytes=size,
                            error=failure)
        _remove_dir(work_dir)
        print(f"[rec {rid}] Fertig: {target} ({size / 1024 / 1024:.1f} MB, "
              f"{len(segments)} Segment(e))", flush=True)


# --- Speicherplatz -------------------------------------------------------

def estimate_bytes(station, minutes):
    """Grobe Groesse einer Aufnahme. Der Stream liefert konstante Bitrate."""
    kbps = int(station.get("bitrate_kbps") or config.DEFAULT_BITRATE_KBPS)
    return int(kbps * 1000 / 8 * int(minutes) * 60)


def free_bytes(path):
    """Freier Platz dort, wo ``path`` liegt bzw. angelegt wuerde."""
    candidate = Path(path)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    try:
        return shutil.disk_usage(str(candidate)).free
    except OSError:
        return None


def same_volume(first, second):
    """Liegen beide Pfade auf demselben Datentraeger?"""
    def device(path):
        candidate = Path(path)
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        try:
            return candidate.stat().st_dev
        except OSError:
            return None

    left, right = device(first), device(second)
    return left is not None and left == right


def check_disk_space(station, minutes):
    """Prueft vor dem Start, ob die Aufnahme ueberhaupt Platz hat.

    Liegen Arbeits- und Zielordner auf demselben Datentraeger, wird kurz vor
    dem Ende doppelt so viel gebraucht: die Segmente bestehen beim
    Zusammenfuegen noch, waehrend die Zieldatei schon geschrieben wird.
    """
    needed = estimate_bytes(station, minutes)
    reserve = config.MIN_FREE_MB * 1024 * 1024
    gemeinsam = same_volume(config.WORK_DIR, config.OUTPUT_DIR)

    ziele = [("Arbeitsordner", config.WORK_DIR,
              needed * 2 if gemeinsam else needed)]
    if not gemeinsam:
        ziele.append(("Zielordner", config.OUTPUT_DIR, needed))

    for bezeichnung, pfad, bedarf in ziele:
        frei = free_bytes(pfad)
        if frei is None:
            continue
        if frei < bedarf + reserve:
            raise ValueError(
                f"Zu wenig Speicherplatz im {bezeichnung} ({pfad}): "
                f"gebraucht werden etwa {_mb(bedarf)}, frei sind {_mb(frei)} "
                f"(davon sollen {_mb(reserve)} frei bleiben)."
            )


def _mb(value):
    size = float(value or 0)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# --- Hilfsfunktionen -----------------------------------------------------

def _drain_stderr(proc, tail):
    """Liest ffmpegs Fehlerausgabe mit, damit die Pipe nicht volllaeuft."""
    try:
        for line in proc.stderr:
            line = line.strip()
            if line:
                tail.append(line)
    except Exception:
        pass


def _last_error_line(tail):
    return tail[-1] if tail else ""


def _segments(work_dir, ext):
    if not work_dir.exists():
        return []
    return sorted(work_dir.glob(f"seg_*.{ext}"))


def _next_segment_number(work_dir, ext):
    highest = -1
    for seg in _segments(work_dir, ext):
        match = re.search(r"seg_(\d+)", seg.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _work_dir_size(work_dir):
    try:
        return sum(f.stat().st_size for f in work_dir.glob("seg_*") if f.is_file())
    except (OSError, AttributeError):
        return 0


def _output_path(record):
    """Zielpfad der fertigen Datei, bei Namensgleichheit durchnummeriert."""
    try:
        started = datetime.fromisoformat(record["started_at"])
    except (TypeError, ValueError):
        started = datetime.now()

    parts = [safe_filename(record["station_name"]) or "Radio"]
    label = safe_filename(record.get("label", ""))
    if label and label.lower() != "manuell":
        parts.append(label)
    parts.append(started.strftime("%Y-%m-%d_%H-%M-%S"))

    stem = "_".join(parts)
    ext = record["ext"]
    target = config.OUTPUT_DIR / f"{stem}.{ext}"
    counter = 2
    while target.exists():
        target = config.OUTPUT_DIR / f"{stem}_{counter}.{ext}"
        counter += 1
    return target


def _join_segments(segments, target, ext):
    """Fuegt die Segmente ohne Neukodierung zu einer Datei zusammen."""
    if len(segments) == 1:
        shutil.move(str(segments[0]), str(target))
        return

    work_dir = segments[0].parent
    listing = work_dir / "segments.txt"
    listing.write_text(
        "".join(f"file '{seg.name}'\n" for seg in segments), encoding="utf-8")

    result = subprocess.run(
        [*config.FFMPEG, "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", listing.name,
         "-c", "copy", "-y", str(target)],
        cwd=str(work_dir),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip()[-500:] or
                           f"ffmpeg endete mit Code {result.returncode}")


def _remove_dir(path, versuche=3):
    """Raeumt das Arbeitsverzeichnis weg.

    Ein einzelner Versuch kann fehlschlagen, wenn eine Datei noch geoeffnet
    ist oder der Datentraeger gerade nicht mitspielt. Bleibt der Ordner
    liegen, belegt er still weiter Platz - deshalb wird es gemeldet.
    """
    ordner = Path(path)
    for nummer in range(versuche):
        shutil.rmtree(ordner, ignore_errors=True)
        if not ordner.exists():
            return True
        if nummer < versuche - 1:
            time.sleep(0.5)
    print(f"[rec] Arbeitsordner {ordner} liess sich nicht raeumen - "
          f"bitte gelegentlich von Hand loeschen", flush=True)
    return False


def _format_span(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# Ein Recorder pro Prozess.
recorder = Recorder()
