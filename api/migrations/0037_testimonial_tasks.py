from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Solo los campos. Pasar los testimonios a tareas va en 0038: en PostgreSQL los
    índices de esta migración se crean al final y no pueden ir después de insertar filas."""

    dependencies = [
        ("api", "0036_profile_testimonials"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="testimonial_for",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="testimonial_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="testimonial_status",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
    ]
