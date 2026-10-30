"""
Asegura que la app de Celery se cargue siempre al iniciar Django.
"""
from .celery import app as celery_app
__all__ = ("celery_app",)