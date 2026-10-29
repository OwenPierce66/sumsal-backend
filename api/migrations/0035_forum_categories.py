from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0034_message_extras"),
    ]

    operations = [
        migrations.AddField(
            model_name="postt",
            name="categories",
            field=models.TextField(blank=True, default=""),
        ),
    ]
