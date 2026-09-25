from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0015_alter_categoryp_unique_together_categoryp_parent_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="favorite_profiles_public",
            field=models.BooleanField(default=False, verbose_name="show favorite profiles"),
        ),
        migrations.AddField(
            model_name="profile",
            name="favorite_tasks_public",
            field=models.BooleanField(default=False, verbose_name="show favorite tasks"),
        ),
        migrations.AddField(
            model_name="favorito",
            name="is_pinned",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="favorito",
            name="position",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="pfavorito",
            name="is_pinned",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="pfavorito",
            name="position",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
