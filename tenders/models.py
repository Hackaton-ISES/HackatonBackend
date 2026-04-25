from django.core.exceptions import ValidationError
from django.db import models


class Company(models.Model):
    name = models.CharField(max_length=255, unique=True)
    total_participations = models.PositiveIntegerField(default=0)
    total_wins = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.name


class Tender(models.Model):
    title = models.CharField(max_length=255)
    organization = models.CharField(max_length=255)
    budget = models.DecimalField(max_digits=14, decimal_places=2)
    average_market_price = models.DecimalField(max_digits=14, decimal_places=2)
    final_price = models.DecimalField(max_digits=14, decimal_places=2)
    participants_count = models.PositiveIntegerField(default=0)
    participants = models.ManyToManyField(Company, related_name='tenders')
    winner_company = models.ForeignKey(
        Company,
        related_name='won_tenders',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField()
    deadline = models.DateTimeField()

    def clean(self):
        if self.deadline <= self.created_at:
            raise ValidationError({'deadline': 'Deadline must be later than created_at.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title
