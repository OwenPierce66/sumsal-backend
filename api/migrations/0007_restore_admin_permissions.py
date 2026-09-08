from django.db import migrations


def restore_admin_permissions(apps, schema_editor):
    Profile = apps.get_model("api", "Profile")
    User = apps.get_model("api", "User")

    admin_user_ids = Profile.objects.filter(role=3).values_list("user_id", flat=True)
    User.objects.filter(id__in=admin_user_ids).update(
        is_staff=True,
        is_superuser=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0006_storyview"),
    ]

    operations = [
        migrations.RunPython(restore_admin_permissions, migrations.RunPython.noop),
    ]