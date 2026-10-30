from django.db import migrations


class Migration(migrations.Migration):
    """Aparte de 0047: en PostgreSQL no se puede cambiar la tabla con datos recién copiados
    en la misma transacción ("pending trigger events")."""

    dependencies = [
        ("api", "0047_profile_activity_levels"),
    ]

    operations = [
        migrations.RemoveField(model_name="profile", name="likes_public"),
        migrations.RemoveField(model_name="profile", name="comments_public"),
        migrations.RemoveField(model_name="profile", name="verifications_public"),
    ]
