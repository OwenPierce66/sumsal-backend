from django.db import migrations


def backfill_shared_story_sources(apps, schema_editor):
    Task = apps.get_model("api", "Task")

    stories = Task.objects.filter(
        pch="historias",
        story_source_task__isnull=True,
    ).exclude(username="")

    for story in stories.iterator():
        source = (
            Task.objects.filter(
                user__username=story.username,
                title=story.title,
            )
            .exclude(pch="historias")
            .order_by("-created_at")
            .first()
        )
        if source:
            story.story_source_task_id = source.id
            story.story_is_shared = True
            story.save(update_fields=["story_source_task", "story_is_shared"])


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0003_task_story_source"),
    ]

    operations = [
        migrations.RunPython(
            backfill_shared_story_sources,
            migrations.RunPython.noop,
        ),
    ]
