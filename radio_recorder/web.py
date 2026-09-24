"""Weboberflaeche des Add-ons (laeuft hinter dem Home-Assistant-Ingress)."""

import os
from datetime import datetime
from pathlib import Path

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_file)

from . import __version__, config, db, directory, probe, scheduler
from . import recorder as recorder_mod
from .recorder import recorder

STATE_LABELS = {
    "running": "laeuft",
    "completed": "fertig",
    "cancelled": "abgebrochen",
    "failed": "fehlgeschlagen",
}

MIME_TYPES = {
    "mp3": "audio/mpeg",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "flac": "audio/flac",
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
            "default_hours": config.DEFAULT_DURATION_HOURS,
            "default_minutes": config.DEFAULT_DURATION_MINUTES,
            "timezone": config.TIMEZONE or "nicht gesetzt",
            "seite": "",
        }

    @app.template_filter("groesse")
    def _size(value):
        return format_size(value)

    @app.template_filter("uhrzeit")
    def _time(value):
        parsed = _parse(value)
        return parsed.strftime("%d.%m.%Y %H:%M") if parsed else "-"

    # --- Aufnahme und Zeitplaene ----------------------------------------

    @app.route("/", methods=["GET"])
    def index():
        stations = db.list_stations()
        namen = {st["key"]: st["name"] for st in stations}
        upcoming = scheduler.next_runs()

        jobs = db.list_jobs()
        for job in jobs:
            job["station_name"] = namen.get(job["station"], job["station"])
            job["duration_text"] = format_duration(job["duration_minutes"])
            job["end_text"] = job["end_time"] or scheduler.end_time_from_duration(
                job["start_time"], job["duration_minutes"])
            job["lead_text"] = _lead_text(job)
            job["weekday_text"] = ", ".join(
                scheduler.WEEKDAY_LABELS.get(d, d) for d in job["weekdays"])
            job["next_run"] = format_next_run(upcoming.get(job["id"]))

        return render_template(
            "index.html",
            seite="aufnahme",
            stations=stations,
            jobs=jobs,
            active=recorder.active(),
            speicher=storage_info(),
        )

    @app.route("/start", methods=["POST"])
    def manual_start():
        try:
            recorder.start(
                station_key=request.form.get("station", ""),
                duration_minutes=_duration_from_form(),
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
            if db.get_station(station) is None:
                raise ValueError("Bitte einen eingetragenen Sender waehlen.")

            start_time = request.form.get("start_time", "")
            scheduler.parse_start_time(start_time)
            weekdays = scheduler.validate_weekdays(request.form.getlist("weekday"))

            end_time = None
            if request.form.get("modus") == "endzeit":
                end_time = (request.form.get("end_time") or "").strip()
                if not end_time:
                    raise ValueError("Bitte eine Endzeit angeben.")
                duration = scheduler.duration_from_end(start_time, end_time)
            else:
                duration = _duration_from_form()

            lead_in = _number("lead_in", 0, 60, "Vorlauf")
            lead_out = _number("lead_out", 0, 60, "Nachlauf")
            if duration + lead_in + lead_out > config.MAX_DURATION_MINUTES:
                raise ValueError(
                    "Dauer samt Vor- und Nachlauf ueberschreitet 24 Stunden.")

            job_id = db.add_job(
                name=name, station=station, start_time=start_time,
                duration_minutes=duration, weekdays=weekdays,
                end_time=end_time, lead_in_minutes=lead_in,
                lead_out_minutes=lead_out,
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

    # --- Sender ----------------------------------------------------------

    @app.route("/stations", methods=["GET"])
    def stations_page():
        suchbegriff = (request.args.get("q") or "").strip()
        treffer, suchfehler = None, None
        if suchbegriff:
            try:
                treffer = directory.search(suchbegriff)
            except directory.DirectoryError as err:
                suchfehler = str(err)

        return render_template(
            "stations.html",
            seite="sender",
            stations=db.list_stations(),
            suchbegriff=suchbegriff,
            treffer=treffer,
            suchfehler=suchfehler,
        )

    @app.route("/stations/add", methods=["POST"])
    def add_station():
        url = (request.form.get("url") or "").strip()
        name = (request.form.get("name") or "").strip()
        try:
            if not url.lower().startswith(("http://", "https://")):
                raise ValueError(
                    "Die Stream-Adresse muss mit http:// oder https:// beginnen.")

            befund = probe.probe_stream(url)
            name = name or befund.get("name") or _name_aus_adresse(url)

            db.add_station(
                name=name,
                url=url,
                ext=befund["ext"],
                codec=befund["codec"],
                bitrate_kbps=_bitrate_waehlen(befund),
                country=(request.form.get("country") or "").strip() or None,
                homepage=(request.form.get("homepage") or "").strip() or None,
                source=(request.form.get("source") or "manual").strip(),
            )

            if befund["fehler"]:
                flash(f"Sender {name!r} angelegt, aber der Stream liess sich "
                      f"nicht pruefen: {befund['fehler']} Es gilt vorerst "
                      f"MP3 mit {config.DEFAULT_BITRATE_KBPS} kbit/s.", "error")
            else:
                flash(f"Sender {name!r} angelegt "
                      f"({befund['codec']}, {_bitrate_waehlen(befund)} kbit/s, "
                      f".{befund['ext']}).", "ok")
        except ValueError as err:
            flash(str(err), "error")
        return redirect(_ingress_base() + "stations")

    @app.route("/stations/recheck/<key>", methods=["POST"])
    def recheck_station(key):
        station = db.get_station(key)
        if station is None:
            flash("Diesen Sender gibt es nicht mehr.", "error")
            return redirect(_ingress_base() + "stations")

        befund = probe.probe_stream(station["url"])
        if befund["fehler"]:
            flash(f"{station['name']}: {befund['fehler']}", "error")
        else:
            db.update_station(
                key,
                ext=befund["ext"],
                codec=befund["codec"],
                bitrate_kbps=_bitrate_waehlen(befund),
                checked_at=datetime.now().isoformat(timespec="seconds"),
            )
            flash(f"{station['name']}: {befund['codec']}, "
                  f"{_bitrate_waehlen(befund)} kbit/s, .{befund['ext']}", "ok")
        return redirect(_ingress_base() + "stations")

    @app.route("/stations/delete/<key>", methods=["POST"])
    def delete_station(key):
        try:
            if db.delete_station(key):
                flash("Sender geloescht.", "ok")
        except ValueError as err:
            flash(str(err), "error")
        return redirect(_ingress_base() + "stations")

    # --- Bibliothek ------------------------------------------------------

    @app.route("/recordings", methods=["GET"])
    def recordings_page():
        eintraege = db.list_recordings(
            states=["completed", "cancelled", "failed"], limit=200)
        gesamt = 0
        for item in eintraege:
            pfad = _recording_path(item, still=True)
            item["vorhanden"] = pfad is not None
            item["dateiname"] = pfad.name if pfad else ""
            item["state_label"] = STATE_LABELS.get(item["state"], item["state"])
            item["duration_text"] = _span(item["started_at"], item["ended_at"])
            if pfad:
                gesamt += item["size_bytes"] or 0

        return render_template("recordings.html", seite="bibliothek",
                               recordings=eintraege, gesamt=gesamt)

    @app.route("/recordings/play/<rid>", methods=["GET"])
    def play_recording(rid):
        eintrag = db.get_recording(rid) or abort(404)
        pfad = _recording_path(eintrag) or abort(404)
        return send_file(str(pfad), mimetype=_mimetype(eintrag["ext"]),
                         conditional=True)

    @app.route("/recordings/download/<rid>", methods=["GET"])
    def download_recording(rid):
        eintrag = db.get_recording(rid) or abort(404)
        pfad = _recording_path(eintrag) or abort(404)
        return send_file(str(pfad), mimetype=_mimetype(eintrag["ext"]),
                         as_attachment=True, download_name=pfad.name,
                         conditional=True)

    @app.route("/recordings/delete/<rid>", methods=["POST"])
    def delete_recording(rid):
        eintrag = db.get_recording(rid)
        if eintrag is None:
            flash("Diese Aufnahme gibt es nicht mehr.", "error")
            return redirect(_ingress_base() + "recordings")
        if eintrag["state"] == "running":
            flash("Diese Aufnahme laeuft noch. Bitte zuerst stoppen.", "error")
            return redirect(_ingress_base() + "recordings")

        pfad = _recording_path(eintrag, still=True)
        if pfad is not None:
            try:
                pfad.unlink()
            except OSError as err:
                flash(f"Datei konnte nicht geloescht werden: {err}", "error")
                return redirect(_ingress_base() + "recordings")

        db.delete_recording(rid)
        flash("Aufnahme geloescht.", "ok")
        return redirect(_ingress_base() + "recordings")

    # --- Schnittstellen --------------------------------------------------

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
            "stations": len(db.list_stations()),
        })

    return app


# --- Hilfsfunktionen -----------------------------------------------------

def _ingress_base():
    base = request.headers.get("X-Ingress-Path", "") or "/"
    if not base.endswith("/"):
        base += "/"
    return base


def _number(field, minimum, maximum, bezeichnung, default=0):
    """Liest eine Zahl aus dem Formular.

    Werte ausserhalb des Bereichs werden abgelehnt und nicht etwa
    zurechtgebogen - sonst nimmt das Add-on bei "25 Stunden" stillschweigend
    nur 24 auf.
    """
    raw = (request.form.get(field) or "").strip()
    try:
        wert = int(raw or default)
    except ValueError:
        raise ValueError(f"{bezeichnung}: {raw!r} ist keine Zahl.") from None
    if wert < minimum or wert > maximum:
        raise ValueError(f"{bezeichnung}: bitte einen Wert zwischen "
                         f"{minimum} und {maximum} angeben.")
    return wert


def _duration_from_form():
    duration = (_number("hours", 0, 24, "Stunden") * 60
                + _number("minutes", 0, 59, "Minuten"))
    if duration < 1 or duration > config.MAX_DURATION_MINUTES:
        raise ValueError("Bitte eine Dauer zwischen 1 Minute und 24 Stunden waehlen.")
    return duration


def _lead_text(job):
    teile = []
    if job.get("lead_in_minutes"):
        teile.append(f"{job['lead_in_minutes']} Min. Vorlauf")
    if job.get("lead_out_minutes"):
        teile.append(f"{job['lead_out_minutes']} Min. Nachlauf")
    return ", ".join(teile)


def _bitrate_waehlen(befund):
    return befund.get("bitrate_kbps") or config.DEFAULT_BITRATE_KBPS


def _name_aus_adresse(url):
    """Notnagel, wenn weder Eingabe noch Stream einen Namen liefern."""
    rest = url.split("//", 1)[-1].split("/", 1)[0]
    return rest or "Sender"


def _mimetype(ext):
    return MIME_TYPES.get((ext or "").lower(), "application/octet-stream")


def _recording_path(eintrag, still=False):
    """Pfad einer Aufnahme - nur innerhalb des Zielordners und nur, wenn da.

    Der Pfad stammt aus der Datenbank, wird aber trotzdem gegen den
    Zielordner geprueft: ausgeliefert wird ausschliesslich, was dort liegt.
    """
    roh = eintrag.get("output_file")
    if not roh:
        return None
    try:
        pfad = Path(roh).resolve()
        wurzel = config.OUTPUT_DIR.resolve()
        pfad.relative_to(wurzel)
    except (OSError, ValueError):
        if not still:
            print(f"[web] Abgelehnt, liegt ausserhalb des Zielordners: {roh}",
                  flush=True)
        return None
    return pfad if pfad.is_file() else None


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
