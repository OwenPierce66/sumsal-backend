"""
Sumsal_Backend/celery.py

Punto de entrada de Celery para la aplicación Django.
Lee la configuración desde django.conf:settings usando el prefijo CELERY_.
"""
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Sumsal_Backend.settings")

app = Celery("Sumsal_Backend")

# Lee toda la configuración de settings.py que empiece con CELERY_
# Ej: CELERY_BROKER_URL -> broker_url
app.config_from_object("django.conf:settings", namespace="CELERY")

# Descubre tareas automáticamente en tasks.py de todas las apps instaladas (api, massaging, etc.)
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")