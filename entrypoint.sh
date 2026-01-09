#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

# Jump into the app directory where manage.py lives
cd /app

# 1. Collect static files only if in Production
if [ "$DEBUG" = "False" ] || [ "$DEBUG" = "0" ]; then
    echo "--- PRODUCTION MODE: Collecting static files ---"
    python manage.py collectstatic --noinput
fi

# 2. Run migrations
echo "--- Running Migrations ---"
python manage.py migrate --noinput

# 3. Choose the Engine
if [ "$DEBUG" = "True" ] || [ "$DEBUG" = "1" ]; then
    echo "--- DEV MODE: Starting Django Runserver ---"
    # exec ensures the process handles signals (like Ctrl+C) correctly
    exec python manage.py runserver 0.0.0.0:8000
else
    echo "--- PRODUCTION MODE: Starting Gunicorn ---"
    exec gunicorn --bind 0.0.0.0:8000 --workers 3 Sumsal_Backend.wsgi:application
fi