from django.db import migrations, models


def copy_switches(apps, schema_editor):
    """Los interruptores de antes (sí / no) pasan a ser niveles (todos / solo yo)."""
    Profile = apps.get_model("api", "Profile")
    for profile in Profile.objects.all():
        levels = dict(profile.activity_levels or {})
        levels.setdefault("likes", "public" if profile.likes_public else "private")
        levels.setdefault("comments", "public" if profile.comments_public else "private")
        levels.setdefault("verifications", "public" if profile.verifications_public else "private")
        profile.activity_levels = levels
        profile.save(update_fields=["activity_levels"])


def restore_switches(apps, schema_editor):
    Profile = apps.get_model("api", "Profile")
    for profile in Profile.objects.all():
        levels = profile.activity_levels or {}
        profile.likes_public = levels.get("likes") == "public"
        profile.comments_public = levels.get("comments") == "public"
        profile.verifications_public = levels.get("verifications", "public") == "public"
        profile.save(update_fields=["likes_public", "comments_public", "verifications_public"])


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0046_profile_feed_public"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="activity_levels",
            field=models.JSONField(blank=True, default=dict, verbose_name="activity visibility"),
        ),
        migrations.RunPython(copy_switches, restore_switches),
    ]
