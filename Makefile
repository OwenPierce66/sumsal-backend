COMPOSE=docker compose
EXEC=$(COMPOSE) exec django-web

.PHONY: up down restart build logs shell migrate migrations superuser clean

logs:
	$(COMPOSE) logs -f --no-log-prefix django-web

translate-file:
	$(EXEC) python manage.py makemessages -l es --ignore=env/* --ignore=venv/* --ignore=node_modules/* --ignore=static/* --ignore=media/* --ignore=htmlcov/*

translate:
	$(EXEC) python manage.py compilemessages
	
# Enter the Django container's terminal
shell:
	$(EXEC) bash

migrate:
	$(EXEC) python manage.py makemigrations api
	$(EXEC) python manage.py migrate

superuser:
	$(EXEC) python manage.py createsuperuser

help:
	$(EXEC) python manage.py help

reset-no-logs:
	$(COMPOSE) down
	$(COMPOSE) up --build

reset:
	$(COMPOSE) down
	$(COMPOSE) up -d
	$(COMPOSE) logs -f --no-log-prefix django-web

reset-medium:
	$(COMPOSE) down
	$(COMPOSE) up -d --build
	$(COMPOSE) logs -f --no-log-prefix django-web

reset-hard:
	$(COMPOSE) down -v
	$(COMPOSE) up -d --build
	$(COMPOSE) logs -f --no-log-prefix django-web

reset-nuclear:
	$(COMPOSE) down -v
	docker builder prune -f
	$(COMPOSE) up -d --build
	$(COMPOSE) logs -f --no-log-prefix django-web
