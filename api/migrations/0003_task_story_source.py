from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0002_task_interaction_score"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="story_is_shared",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="task",
            name="story_source_task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="story_copies",
                to="api.task",
            ),
        ),
    ]
