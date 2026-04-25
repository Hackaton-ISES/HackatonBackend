# Generated manually for Tender Guardian schema expansion.

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('tenders', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='completed_projects',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='company',
            name='created_at',
            field=models.DateTimeField(default=timezone.now, auto_now_add=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='company',
            name='failed_projects',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='company',
            name='updated_at',
            field=models.DateTimeField(default=timezone.now, auto_now=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tender',
            name='added_at',
            field=models.DateTimeField(default=timezone.now, auto_now_add=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tender',
            name='category',
            field=models.CharField(default='General', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tender',
            name='is_completed_by_winner',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tender',
            name='status',
            field=models.CharField(
                choices=[('active', 'Active'), ('completed', 'Completed'), ('cancelled', 'Cancelled')],
                default='active',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='tender',
            name='updated_at',
            field=models.DateTimeField(default=timezone.now, auto_now=True),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='tender',
            name='participants',
            field=models.ManyToManyField(blank=True, related_name='tenders', to='tenders.company'),
        ),
        migrations.CreateModel(
            name='TenderRiskAnalysis',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_score', models.PositiveIntegerField(default=0)),
                ('risk_level', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], default='low', max_length=10)),
                ('price_score', models.PositiveIntegerField(default=0)),
                ('company_history_score', models.PositiveIntegerField(default=0)),
                ('consecutive_wins_score', models.PositiveIntegerField(default=0)),
                ('participants_score', models.PositiveIntegerField(default=0)),
                ('analyzed_at', models.DateTimeField(auto_now=True)),
                ('tender', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='risk_analysis', to='tenders.tender')),
            ],
            options={
                'ordering': ['-analyzed_at'],
            },
        ),
        migrations.CreateModel(
            name='RiskReason',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField()),
                ('score', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('analysis', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reasons', to='tenders.tenderriskanalysis')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
    ]
