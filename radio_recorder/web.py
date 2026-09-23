"""Weboberflaeche des Add-ons (laeuft hinter dem Home-Assistant-Ingress)."""

import os
from datetime import datetime

from flask import (Flask, flash, jsonify, redirect, render_template, request)

from . import __version__, config, db, scheduler
from . import recorder as recorder_mod
from .recorder import recorder

STATE_LABELS = {
    "running": "laeuft",
    "completed": "fertig",
    "cancelled": "abgebrochen",
    "failed": "fehlgeschlagen",
}


def create_app():
    app = Flask(__name__)
    # Wird nur fuer kurzlebige Hinweismeldungen gebraucht.
    app.secret_key = os.urandom(24)

    @app.context_processor
    def _defaults():
        return {
            "base": _ingress_base(),
            "version": __version__,
            "weekdays": scheduler.WEEKDAYS,
            "stations": config.station_choices(),
            "default_hours": config.DEFAULT_DURATION_HOURS,
            "default_minutes": config.DEFAULT_DURATION_MINUTES,
            "output_dir": str(config.OUTPUT_DIR),
            "timezone": config.TIMEZONE or "nicht gesetzt",
        }

    @app.template_filter("groesse")
    def _size(value):
        return format_size(value)

    @app.template_filter("uhrzeit")
    def _time(value):
        parsed = _parse(value)
        return parsed.strftime("%d.%m.%Y %H:%M") if parsed else "-"

    @app.route("/", methods=["GET"])
    def index():
        jobs = db.list_jobs()
        upcoming = scheduler.next_runs()
        for job in jobs:
            job["duration_text"] = format_duration(job["duration_minutes"])
            job["weekday_text"] = ", ".join(
                scheduler.WEEKDAY_LABELS.get(d, d) for d in job["weekdays"])
            job["next_run"] = format_next_run(upcoming.get(job["id"]))

        history = db.list_recordings(
            states=["completed", "cancelled", "failed"], limit=20)
        for item in history:
            item["state_label"] = STATE_LABELS.get(item["state"], item["state"])
            item["duration_text"] = _span(item["started_at"], item["ended_at"])

        return render_template(
            "index.html",
            jobs=jobs,
            active=recorder.active(),
            history=history,
            speicher=storage_info(),
            station_labels=dict(config.station_choices()),
        )

    @app.route("/start", methods=["POST"])
    def manual_start():
        try:
            duration = _duration_from_form()
            recorder.start(
                station_key=request.form.get("station", ""),
                duration_minutes=duration,
                label=request.form.get("label", "").strip() or "Manuell",
            )
        except ValueError as err:
            flash(str(err), "error")
        except Exception as err:
            flash(f"Aufnahme konnte nicht gestartet werden: {err}", "error")
        return redirect(_ingress_base())

    @app.route("/stop/<rid>", methods=["POST"])
    def manual_stop(rid):
        if not recorder.stop(rid):
            flash("Diese Aufnahme laeuft nicht mehr.", "error")
        return redirect(_ingress_base())

    @app.route("/schedule/add", methods=["POST"])
    def add_schedule():
        try:
            name = request.form.get("name", "").strip()
            if not name:
                raise ValueError("Bitte einen Namen vergeben.")
            station = request.form.get("station", "")
            config.get_station(station)
            start_time = request.form.get("start_time", "")
            scheduler.parse_start_time(start_time)
            weekdays = scheduler.validate_weekdays(request.form.getlist("weekday"))
            duration = _duration_from_form()

            job_id = db.add_job(
                name=name, station=station, start_time=start_time,
                duration_minutes=duration, weekdays=weekdays,
            )
            scheduler.schedule(db.get_job(job_id))
            flash(f"Zeitplan {name!r} gespeichert.", "ok")
        except ValueError as err:
            flash(str(err), "error")
        return redirect(_ingress_base())

    @app.route("/schedule/delete/<job_id>", methods=["POST"])
    def delete_schedule(job_id):
        scheduler.unschedule(job_id)
        if db.delete_job(job_id):
            flash("Zeitplan geloescht.", "ok")
        return redirect(_ingress_base())

    @app.route("/schedule/toggle/<job_id>", methods=["POST"])
    def toggle_schedule(job_id):
        job = db.get_job(job_id)
        if job:
            enabled = not job["enabled"]
            db.set_job_enabled(job_id, enabled)
            if enabled:
                try:
                    scheduler.schedule(db.get_job(job_id))
                except ValueError as err:
                    flash(str(err), "error")
            else:
                scheduler.unschedule(job_id)
        return redirect(_ingress_base())

    @app.route("/api/status", methods=["GET"])
    def api_status():
        """Wird von der Oberflaeche zum Aktualisieren abgefragt."""
        return jsonify({
            "active": [
                {
                    "id": item["id"],
                    "station": item["station_name"],
                    "elapsed": item["elapsed"],
                    "remaining": item["remaining"],
                    "size": format_size(item["size_bytes"]),
                    "resume_count": item["resume_count"],
                    "retry_count": item["retry_count"],
                }
                for item in recorder.active()
            ],
            "server_time": datetime.now().strftime("%H:%M:%S"),
        })

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "ok": True,
            "version": __version__,
            "timezone": config.TIMEZONE,
            "active_recordings": len(recorder.active()),
        })

    return app


# --- Hilfsfunktionen -----------------------------------------------------

def _ingress_base():
    base = request.headers.get("X-Ingress-Path", "") or "/"
    if not base.endswith("/"):
        base += "/"
    return base


def _duration_from_form():
    def _number(field):
        raw = (request.form.get(field) or "0").strip()
        try:
            return int(raw or 0)
        except ValueError:
            raise ValueError(f"{field!r} muss eine Zahl sein.") from None

    duration = _number("hours") * 60 + _number("minutes")
    if duration < 1 or duration > config.MAX_DURATION_MINUTES:
        raise ValueError("Bitte eine Dauer zwischen 1 Minute und 24 Stunden waehlen.")
    return duration


def _parse(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _span(start, end):
    first, second = _parse(start), _parse(end)
    if not first or not second:
        return "-"
    return format_duration(int((second - first).total_seconds() // 60))


def storage_info():
    """Platzangaben fuer die Oberflaeche, inklusive grober Reichweite."""
    reserve = config.MIN_FREE_MB * 1024 * 1024
    gemeinsam = recorder_mod.same_volume(config.WORK_DIR, config.OUTPUT_DIR)
    frei_arbeit = recorder_mod.free_bytes(config.WORK_DIR)
    frei_ziel = recorder_mod.free_bytes(config.OUTPUT_DIR)

    # Beim Zusammenfuegen bestehen Segmente und Zieldatei kurz gleichzeitig -
    # auf einem gemeinsamen Datentraeger zaehlt also der doppelte Bedarf.
    nutzbar = None
    if frei_arbeit is not None:
        nutzbar = max(0, frei_arbeit - reserve)
        if gemeinsam:
            nutzbar //= 2
        elif frei_ziel is not None:
            nutzbar = min(nutzbar, max(0, frei_ziel - reserve))

    pro_stunde = config.DEFAULT_BITRATE_KBPS * 1000 / 8 * 3600
    stunden = (nutzbar / pro_stunde) if nutzbar else 0

    return {
        "output_dir": str(config.OUTPUT_DIR),
        "work_dir": str(config.WORK_DIR),
        "gemeinsam": gemeinsam,
        "frei_arbeit": format_size(frei_arbeit) if frei_arbeit is not None else "?",
        "frei_ziel": format_size(frei_ziel) if frei_ziel is not None else "?",
        "reserve": format_size(reserve),
        "reichweite": f"{stunden:.0f}" if stunden >= 1 else "unter 1",
        "bitrate": config.DEFAULT_BITRATE_KBPS,
        "knapp": stunden < 2,
    }


def format_next_run(moment):
    """Naechster Lauf mit deutschem Wochentag - strftime waere hier englisch."""
    if moment is None:
        return "-"
    tag = scheduler.WEEKDAYS[moment.weekday()][1]
    return f"{tag} {moment.strftime('%d.%m. %H:%M')}"


def format_duration(minutes):
    minutes = max(0, int(minutes or 0))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} Std. {rest} Min."
    if hours:
        return f"{hours} Std."
    return f"{rest} Min."


def format_size(value):
    size = float(value or 0)
    if size < 1024:
        return f"{int(size)} B"
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024:
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"
