# Generated by Django 5.1.1 on 2024-10-03 09:20

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("machine", "0002_alter_machine_stats_installedbinary"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="installedbinary",
            options={
                "verbose_name": "Installed Binary",
                "verbose_name_plural": "Installed Binaries",
            },
        ),
        migrations.AddField(
            model_name="installedbinary",
            name="num_uses_failed",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="installedbinary",
            name="num_uses_succeeded",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="machine",
            name="num_uses_failed",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="machine",
            name="num_uses_succeeded",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="networkinterface",
            name="num_uses_failed",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="networkinterface",
            name="num_uses_succeeded",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
