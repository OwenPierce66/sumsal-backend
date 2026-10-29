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

# Solo un contenedor aplica las migraciones: si dos las corren a la vez (django y
# celery-worker) chocan creando las mismas tablas y uno se cae.
if [ "$SKIP_MIGRATIONS" = "true" ]; then
  echo "--- Migraciones omitidas: las aplica el servicio django ---"
else
  echo "--- Aplicando migraciones ---"
  python manage.py migrate --noinput
fi

if [ "$DEBUG" = "False" ] || [ "$DEBUG" = "0" ] || [ -n "$RENDER" ]; then
  echo "--- Recolectando archivos estáticos ---"
  python manage.py collectstatic --noinput || true
fi

# El worker de Celery (servicio celery-worker) trae su propio comando: se ejecuta tal
# cual en vez del servidor web. Solo para "celery": el CMD por defecto del Dockerfile
# también llega aquí y en producción debe seguir arrancando gunicorn.
if [ "$1" = "celery" ]; then
  echo "--- Iniciando worker: $* ---"
  exec "$@"
fi

TARGET_PORT="${PORT:-8000}"
if [ "$DEBUG" = "True" ] || [ "$DEBUG" = "1" ]; then
  echo "--- Iniciando en modo desarrollo en puerto $TARGET_PORT ---"
  exec python manage.py runserver 0.0.0.0:$TARGET_PORT
else
  echo "--- Iniciando Gunicorn en puerto $TARGET_PORT con access log ---"
  exec gunicorn Sumsal_Backend.wsgi:application --bind 0.0.0.0:$TARGET_PORT --workers 2 --timeout 120 \
    --access-logfile - \
    --access-logformat '%(t)s "%(m)s %(U)s" %(s)s %(b)s %(D)s'
fi