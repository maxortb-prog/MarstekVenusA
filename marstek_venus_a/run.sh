#!/usr/bin/with-contenv bashio
# MarstekVenusA add-on entry point
bashio::log.info "Starting MarstekVenusA bridge ..."
exec python3 -u /app/main.py
