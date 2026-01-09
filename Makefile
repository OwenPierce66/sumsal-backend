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
# logs:
# 	$(COMPOSE) logs -f

# Specific logs for Django
logs:
# 	$(COMPOSE) logs -f django-web
	$(COMPOSE) logs -f --no-log-prefix django-web

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

reset:
	$(COMPOSE) down
	$(COMPOSE) up -d
	$(COMPOSE) logs -f --no-log-prefix django-web

# Medium: Use this when you add a new Python library or change a config file
reset-medium:
	$(COMPOSE) down
	$(COMPOSE) up -d --build
	$(COMPOSE) logs -f --no-log-prefix django-web

# Nuclear: Use this when the database is a mess or migrations are failing
reset-hard:
	$(COMPOSE) down -v
	$(COMPOSE) up -d --build
	$(COMPOSE) logs -f --no-log-prefix django-web

a-reset:
	$(COMPOSE) down
	$(COMPOSE) up --build