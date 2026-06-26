#!/bin/sh
# Crea el superusuario al primer arranque si se pasaron las variables de entorno
if [ -n "$PB_SUPERUSER_EMAIL" ] && [ -n "$PB_SUPERUSER_PASSWORD" ]; then
    /pb/pocketbase superuser upsert "$PB_SUPERUSER_EMAIL" "$PB_SUPERUSER_PASSWORD" 2>/dev/null || true
fi

exec /pb/pocketbase serve --http=0.0.0.0:8090
