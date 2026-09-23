import json
import os
import re
import signal
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify, redirect, render_template_string, request

APP = Flask(__name__)

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/media/Musick/Radioaufnahmen"))
DEFAULT_DURATION_HOURS = int(os.environ.get("DEFAULT_DURATION_HOURS", "4"))
DEFAULT_DURATION_MINUTES = int(os.environ.get("DEFAULT_DURATION_MINUTES", "0"))
DATA_DIR = Path("/data")
JOBS_FILE = DATA_DIR / "jobs.json"

STATIONS = {
    "sunshine_live": {
        "name": "SUNSHINE LIVE",
        "url": "https://stream.sunshine-live.de/live/mp3-192/stream.sunshine-live.de/",
        "ext": "mp3",
    }
}

process_lock = threading.Lock()
active_processes = {}
scheduler = BackgroundScheduler()
scheduler.start()

def safe_filename(text):
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())
    return text.strip("_") or "Radio"

def load_jobs():
    if not JOBS_FILE.exists():
        return []
    try:
        return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_jobs(jobs):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")

def recording_filename(station_key):
    st = STATIONS[station_key]
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return OUTPUT_DIR / f"{safe_filename(st['name'])}_{stamp}.{st['ext']}"

def stop_recording(recording_id):
    with process_lock:
        entry = active_processes.get(recording_id)
        if not entry:
            return False
        proc = entry["proc"]
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        active_processes.pop(recording_id, None)
        return True

def start_recording(station_key="sunshine_live", duration_minutes=None, label=None):
    if station_key not in STATIONS:
        raise ValueError("Unbekannter Sender")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    st = STATIONS[station_key]
    out = recording_filename(station_key)
    rid = str(uuid.uuid4())[:8]

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "10",
        "-reconnect_on_network_error", "1",
        "-reconnect_on_http_error", "4xx,5xx",
        "-i", st["url"],
        "-vn",
        "-c:a", "copy",
    ]

    if duration_minutes:
        cmd += ["-t", str(int(duration_minutes) * 60)]

    cmd += ["-y", str(out)]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True
    )

    with process_lock:
        active_processes[rid] = {
            "proc": proc,
            "station": st["name"],
            "file": str(out),
            "started": datetime.now().isoformat(timespec="seconds"),
            "duration_minutes": duration_minutes,
            "label": label or "",
        }

    def watcher():
        try:
            _, stderr = proc.communicate()
        finally:
            with process_lock:
                active_processes.pop(rid, None)
            if proc.returncode not in (0, 255) and stderr:
                print(f"FFmpeg Fehler [{rid}]: {stderr[-2000:]}", flush=True)

    threading.Thread(target=watcher, daemon=True).start()
    return rid, out

def schedule_job(job):
    trigger = CronTrigger(
        day_of_week=",".join(job["weekdays"]),
        hour=int(job["start_time"].split(":")[0]),
        minute=int(job["start_time"].split(":")[1]),
    )
    scheduler.add_job(
        lambda: start_recording(job["station"], job["duration_minutes"], job["name"]),
        trigger=trigger,
        id=job["id"],
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,
    )

for job in load_jobs():
    if job.get("enabled", True):
        try:
            schedule_job(job)
        except Exception as err:
            print(f"Zeitplan konnte nicht geladen werden: {err}", flush=True)

HTML = """
<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Radio Recorder</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#111827;color:#f3f4f6;margin:0;padding:20px}
.wrap{max-width:980px;margin:auto}
.card{background:#1f2937;border-radius:14px;padding:18px;margin-bottom:16px;box-shadow:0 4px 16px #0004}
h1,h2{margin-top:0}
input,select,button{font:inherit;border-radius:9px;border:1px solid #4b5563;padding:10px;background:#111827;color:#fff}
button{cursor:pointer;background:#2563eb;border:0}
button.danger{background:#b91c1c}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.small{font-size:.9rem;color:#cbd5e1}
.status{padding:10px 12px;background:#0f172a;border-radius:10px;margin:8px 0}
table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:9px;border-bottom:1px solid #374151}
label{display:block;margin-bottom:5px}
.weekdays label{display:inline-flex;align-items:center;gap:4px;margin-right:10px}
</style>
</head>
<body><div class="wrap">
<h1>📻 Radio Recorder</h1>

<div class="card">
<h2>Manuelle Aufnahme</h2>
<form method="post" action="{{ base }}start">
<div class="grid">
<div><label>Sender</label>
<select name="station">
{% for key, st in stations.items() %}<option value="{{key}}">{{st.name}}</option>{% endfor %}
</select></div>
<div><label>Stunden</label><input type="number" min="0" max="24" name="hours" value="{{default_hours}}"></div>
<div><label>Minuten</label><input type="number" min="0" max="59" name="minutes" value="{{default_minutes}}"></div>
</div>
<p><button type="submit">⏺ Aufnahme starten</button></p>
</form>

{% if active %}
<h3>Laufende Aufnahmen</h3>
{% for rid, rec in active.items() %}
<div class="status">
<b>{{rec.station}}</b> – gestartet {{rec.started}}<br>
<span class="small">Läuft seit: {{rec.elapsed}}</span><br>
<span class="small">{{rec.file}}</span>
<form method="post" action="{{ base }}stop/{{rid}}" style="margin-top:8px"><button class="danger">⏹ Stoppen</button></form>
</div>
{% endfor %}
{% else %}
<p class="small">Zurzeit läuft keine Aufnahme.</p>
{% endif %}
</div>

<div class="card">
<h2>Zeitplan hinzufügen</h2>
<form method="post" action="{{ base }}schedule/add">
<div class="grid">
<div><label>Name</label><input name="name" placeholder="z. B. Freitag Nacht" required></div>
<div><label>Sender</label>
<select name="station">
{% for key, st in stations.items() %}<option value="{{key}}">{{st.name}}</option>{% endfor %}
</select></div>
<div><label>Startzeit</label><input type="time" name="start_time" required></div>
<div><label>Stunden</label><input type="number" min="0" max="24" name="hours" value="{{default_hours}}" required></div>
<div><label>Minuten</label><input type="number" min="0" max="59" name="minutes" value="{{default_minutes}}" required></div>
</div>
<p class="weekdays">
<label><input type="checkbox" name="weekday" value="mon">Mo</label>
<label><input type="checkbox" name="weekday" value="tue">Di</label>
<label><input type="checkbox" name="weekday" value="wed">Mi</label>
<label><input type="checkbox" name="weekday" value="thu">Do</label>
<label><input type="checkbox" name="weekday" value="fri">Fr</label>
<label><input type="checkbox" name="weekday" value="sat">Sa</label>
<label><input type="checkbox" name="weekday" value="sun">So</label>
</p>
<button type="submit">➕ Zeitplan speichern</button>
</form>
</div>

<div class="card">
<h2>Gespeicherte Zeitpläne</h2>
{% if jobs %}
<table>
<tr><th>Name</th><th>Start</th><th>Tage</th><th>Dauer</th><th></th></tr>
{% for job in jobs %}
<tr>
<td>{{job.name}}</td>
<td>{{job.start_time}}</td>
<td>{{job.weekdays|join(', ')}}</td>
<td>{{job.duration_text}}</td>
<td><form method="post" action="{{ base }}schedule/delete/{{job.id}}"><button class="danger">Löschen</button></form></td>
</tr>
{% endfor %}
</table>
{% else %}<p class="small">Noch keine Zeitpläne gespeichert.</p>{% endif %}
</div>

<div class="card">
<h2>Speicher</h2>
<p><b>Zielordner:</b> {{output_dir}}</p>
<p class="small">Aufnahmen bis 24 Stunden werden unterstützt.</p>
</div>
</div></body>
</html>
"""

def ingress_base():
    base = request.headers.get("X-Ingress-Path", "/")
    if not base.endswith("/"):
        base += "/"
    return base

@APP.route("/", methods=["GET"])
def index():
    jobs = load_jobs()
    now = datetime.now()

    with process_lock:
        active = {}
        for rid, rec in active_processes.items():
            item = {k: v for k, v in rec.items() if k != "proc"}
            try:
                started = datetime.fromisoformat(item["started"])
                total = int((now - started).total_seconds())
                h, rem = divmod(total, 3600)
                m, s = divmod(rem, 60)
                item["elapsed"] = f"{h:02d}:{m:02d}:{s:02d}"
            except Exception:
                item["elapsed"] = "-"
            active[rid] = item

    for job in jobs:
        mins = int(job.get("duration_minutes", 0))
        h, m = divmod(mins, 60)
        job["duration_text"] = f"{h} Std. {m} Min." if m else f"{h} Std."

    return render_template_string(
        HTML,
        stations=STATIONS,
        active=active,
        jobs=jobs,
        output_dir=str(OUTPUT_DIR),
        default_hours=DEFAULT_DURATION_HOURS,
        default_minutes=DEFAULT_DURATION_MINUTES,
        base=ingress_base(),
    )

@APP.route("/start", methods=["POST"])
def manual_start():
    station = request.form.get("station", "sunshine_live")
    hours = int(request.form.get("hours", DEFAULT_DURATION_HOURS))
    minutes = int(request.form.get("minutes", DEFAULT_DURATION_MINUTES))
    duration = hours * 60 + minutes
    if duration < 1 or duration > 1440:
        return "Bitte eine Dauer zwischen 1 Minute und 24 Stunden wählen.", 400
    start_recording(station, duration, "Manuell")
    return redirect(ingress_base())

@APP.route("/stop/<rid>", methods=["POST"])
def manual_stop(rid):
    stop_recording(rid)
    return redirect(ingress_base())

@APP.route("/schedule/add", methods=["POST"])
def add_schedule():
    weekdays = request.form.getlist("weekday")
    if not weekdays:
        return "Bitte mindestens einen Wochentag auswählen.", 400

    hours = int(request.form.get("hours", 0))
    minutes = int(request.form.get("minutes", 0))
    duration = hours * 60 + minutes
    if duration < 1 or duration > 1440:
        return "Bitte eine Dauer zwischen 1 Minute und 24 Stunden wählen.", 400

    job = {
        "id": "job_" + str(uuid.uuid4())[:10],
        "name": request.form["name"].strip(),
        "station": request.form.get("station", "sunshine_live"),
        "start_time": request.form["start_time"],
        "duration_minutes": duration,
        "weekdays": weekdays,
        "enabled": True,
    }

    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)
    schedule_job(job)
    return redirect(ingress_base())

@APP.route("/schedule/delete/<job_id>", methods=["POST"])
def delete_schedule(job_id):
    jobs = [j for j in load_jobs() if j.get("id") != job_id]
    save_jobs(jobs)
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    return redirect(ingress_base())

@APP.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    APP.run(host="0.0.0.0", port=8099, threaded=True)
