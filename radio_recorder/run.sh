#!/usr/bin/with-contenv bashio
set -e

export OUTPUT_DIR="$(bashio::config 'output_dir')"
export DEFAULT_DURATION_HOURS="$(bashio::config 'default_duration_hours')"
export DEFAULT_DURATION_MINUTES="$(bashio::config 'default_duration_minutes')"
export SEGMENT_MINUTES="$(bashio::config 'segment_minutes')"
export MIN_FREE_MB="$(bashio::config 'min_free_mb')"

# Arbeitsordner ist optional. Ohne Angabe bleiben die Zwischenstuecke im
# Add-on-Speicher unter /data/work.
if bashio::config.has_value 'work_dir'; then
    export WORK_DIR="$(bashio::config 'work_dir')"
    mkdir -p "${WORK_DIR}" || bashio::log.warning "Arbeitsordner ${WORK_DIR} nicht anlegbar"
fi

# --- Zeitzone ---------------------------------------------------------------
# Der Supervisor reicht TZ normalerweise selbst in den Container. Wir setzen
# den Wert hier trotzdem ausdruecklich und legen zusaetzlich /etc/localtime an,
# damit Python und APScheduler in jedem Fall dieselbe Zeitzone verwenden wie
# Home Assistant. Ohne das liefen Zeitplaene in UTC.
if [ -z "${TZ:-}" ]; then
    TZ="$(bashio::info.timezone 2>/dev/null || true)"
fi

if [ -n "${TZ:-}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    cp "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
    export TZ
    bashio::log.info "Zeitzone: ${TZ}"
else
    bashio::log.warning "Zeitzone konnte nicht ermittelt werden."
    bashio::log.warning "Zeitplaene laufen dann in UTC und sind ggf. verschoben."
fi

# --- Zielordner -------------------------------------------------------------
if ! mkdir -p "${OUTPUT_DIR}"; then
    bashio::log.warning "Zielordner ${OUTPUT_DIR} konnte nicht angelegt werden."
    bashio::log.warning "Aufnahmen werden fehlschlagen, bis er erreichbar ist."
fi

bashio::log.info "Radio Recorder startet"
bashio::log.info "Aufnahmen werden gespeichert unter: ${OUTPUT_DIR}"

exec python3 /app/app.py
