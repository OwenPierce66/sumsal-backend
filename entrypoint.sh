#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

# Espera a que la base de datos esté lista usando netcat
echo "--- Esperando a que la base de datos inicie... ---"
while ! nc -z db 5432; do
  sleep 0.1
done
echo "--- ¡Base de datos iniciada! ---"

# Inicia el comando principal (el CMD del Dockerfile)
echo "--- Iniciando el servidor ---"
exec "$@"