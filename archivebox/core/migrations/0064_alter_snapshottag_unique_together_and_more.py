# Generated by Django 5.0.6 on 2024-08-20 03:50

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0063_snapshottag_tag_alter_snapshottag_old_tag'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='snapshottag',
            unique_together=set(),
        ),
        migrations.AlterField(
            model_name='snapshottag',
            name='tag',
            field=models.ForeignKey(db_column='tag_id', on_delete=django.db.models.deletion.CASCADE, to='core.tag', to_field='id'),
        ),
        migrations.AlterUniqueTogether(
            name='snapshottag',
            unique_together={('snapshot', 'tag')},
        ),
    ]
