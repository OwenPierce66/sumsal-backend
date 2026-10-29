from django.db import migrations


def testimonials_to_tasks(apps, schema_editor):
    """Cada testimonio escrito en un perfil pasa a ser una publicación (tarea "testimonios").
    Conserva su id para que sus notificaciones sigan funcionando."""
    ProfileTestimonial = apps.get_model("api", "ProfileTestimonial")
    Task = apps.get_model("api", "Task")
    for item in ProfileTestimonial.objects.select_related("author"):
        Task.objects.create(
            id=item.id,
            user_id=item.author_id,
            username=item.author.username or "",
            title="Testimonio",
            description=item.text,
            pch="testimonios",
            testimonial_for_id=item.recipient_id,
            testimonial_status=item.status,
        )
        Task.objects.filter(pk=item.id).update(created_at=item.created_at)


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0037_testimonial_tasks"),
    ]

    operations = [
        migrations.RunPython(testimonials_to_tasks, migrations.RunPython.noop),
        migrations.DeleteModel(name="ProfileTestimonial"),
    ]
