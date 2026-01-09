# Define variables
COMPOSE=docker compose
EXEC=$(COMPOSE) exec django-web

.PHONY: up down restart build logs shell migrate migrations superuser clean

# Start the project
up:
	$(COMPOSE) up -d

# Start and build (for when you change requirements.txt)
build:
	$(COMPOSE) up -d --build

# Stop the project
down:
	$(COMPOSE) down

# View logs
logs:
	$(COMPOSE) logs -f

# Specific logs for Django
logs-web:
	$(COMPOSE) logs -f django-web

# Enter the Django container's terminal
shell:
	$(EXEC) bash

# Database Shortcuts
migrate:
	$(EXEC) python manage.py migrate

migrations:
	$(EXEC) python manage.py makemigrations

superuser:
	$(EXEC) python manage.py createsuperuser

# The "Reset Everything" button
reset:
# 	$(COMPOSE) down -v
	$(COMPOSE) up --build