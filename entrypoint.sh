#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

# Espera a que la base de datos esté lista usando netcat
echo "--- Esperando a que la base de datos inicie... ---"
while ! nc -z db 5432; do
  sleep 0.1
done
echo "--- ¡Base de datos iniciada! ---"

# 1. Collect static files only if in Production
if [ "$DEBUG" = "False" ] || [ "$DEBUG" = "0" ]; then
    echo "--- PRODUCTION MODE: Collecting static files ---"
    /usr/local/bin/python manage.py collectstatic --noinput
fi

# 2. Run migrations
echo "--- Running Migrations ---"
/usr/local/bin/python manage.py migrate --noinput

# 3. Inicia el comando principal (el CMD del Dockerfile)
echo "--- Iniciando el servidor ---"
exec "$@"