#!/bin/sh
set -e

cd /app

if [ "$BYPASS_DB_WAIT" = "true" ] || [ "$BYPASS_PGBOUNCER" = "true" ] || [ -n "$RENDER" ]; then
  echo "--- Entorno Cloud detectado: omitiendo espera de contenedor local db ---"
else
  echo "--- Esperando a que la base de datos local inicie... ---"
  while ! nc -z db 5432; do
    sleep 0.5
  done
  echo "--- ¡Base de datos iniciada! ---"
fi

echo "--- Aplicando migraciones ---"
python manage.py migrate --noinput

if [ "$DEBUG" = "False" ] || [ "$DEBUG" = "0" ] || [ -n "$RENDER" ]; then
  echo "--- Recolectando archivos estáticos ---"
  python manage.py collectstatic --noinput || true
fi

TARGET_PORT="${PORT:-8000}"
if [ "$DEBUG" = "True" ] || [ "$DEBUG" = "1" ]; then
  echo "--- Iniciando en modo desarrollo en puerto $TARGET_PORT ---"
  exec python manage.py runserver 0.0.0.0:$TARGET_PORT
else
  echo "--- Iniciando Gunicorn en puerto $TARGET_PORT ---"
  exec gunicorn Sumsal_Backend.wsgi:application --bind 0.0.0.0:$TARGET_PORT --workers 2 --timeout 120
fi