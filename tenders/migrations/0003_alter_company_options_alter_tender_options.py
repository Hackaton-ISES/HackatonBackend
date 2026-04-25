# Generated manually to align model Meta options with migrations.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tenders', '0002_expand_tender_guardian_models'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='company',
            options={'ordering': ['name']},
        ),
        migrations.AlterModelOptions(
            name='tender',
            options={'ordering': ['-created_at', '-id']},
        ),
    ]
