#!/usr/bin/with-contenv bashio
set -e

export OUTPUT_DIR="$(bashio::config 'output_dir')"
export DEFAULT_DURATION_HOURS="$(bashio::config 'default_duration_hours')"
export DEFAULT_DURATION_MINUTES="$(bashio::config 'default_duration_minutes')"

mkdir -p "${OUTPUT_DIR}"

bashio::log.info "Radio Recorder startet"
bashio::log.info "Aufnahmen werden gespeichert unter: ${OUTPUT_DIR}"

exec python3 /app/app.py
