from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models


ZERO_DECIMAL = Decimal('0')
HUNDRED_DECIMAL = Decimal('100')


class Company(models.Model):
    external_id = models.CharField(max_length=50, unique=True, blank=True, default='')
    name = models.CharField(max_length=255, unique=True)
    total_participations = models.PositiveIntegerField(default=0)
    total_wins = models.PositiveIntegerField(default=0)
    completed_projects = models.PositiveIntegerField(default=0)
    failed_projects = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.external_id:
            slug = ''.join(char.lower() if char.isalnum() else '-' for char in self.name).strip('-')
            self.external_id = f'c-{slug[:40] or "company"}'
        super().save(*args, **kwargs)

    @property
    @admin.display(description='Failure Rate')
    def failure_rate(self) -> Decimal:
        if self.total_wins == 0:
            return ZERO_DECIMAL
        return (
            (Decimal(self.failed_projects) / Decimal(self.total_wins)) * HUNDRED_DECIMAL
        ).quantize(Decimal('0.01'))

    @property
    @admin.display(description='Win Rate')
    def win_rate(self) -> Decimal:
        if self.total_participations == 0:
            return ZERO_DECIMAL
        return (
            (Decimal(self.total_wins) / Decimal(self.total_participations)) * HUNDRED_DECIMAL
        ).quantize(Decimal('0.01'))

    def update_statistics(self, save: bool = True) -> None:
        self.total_participations = self.tenders.distinct().count()
        self.total_wins = self.won_tenders.count()
        self.completed_projects = self.won_tenders.filter(
            status=Tender.Status.COMPLETED,
            is_completed_by_winner=True,
        ).count()
        self.failed_projects = self.won_tenders.filter(
            status=Tender.Status.COMPLETED,
            is_completed_by_winner=False,
        ).count()
        if save:
            self.save(
                update_fields=[
                    'total_participations',
                    'total_wins',
                    'completed_projects',
                    'failed_projects',
                    'updated_at',
                ]
            )


class UserProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        COMPANY = 'company', 'Company'

    external_id = models.CharField(max_length=50, unique=True, blank=True, default='')
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.COMPANY)
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='user_profiles',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__username']

    def __str__(self) -> str:
        return f'{self.user.username} ({self.role})'

    def save(self, *args, **kwargs):
        if not self.external_id:
            if self.role == self.Role.ADMIN:
                self.external_id = f'u-{self.user.username.lower()}'
            elif self.company_id:
                self.external_id = self.company.external_id
            else:
                self.external_id = f'u-{self.user.username.lower()}'
        super().save(*args, **kwargs)


class Tender(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    external_id = models.CharField(max_length=50, unique=True, blank=True, default='')
    title = models.CharField(max_length=255)
    organization = models.CharField(max_length=255)
    category = models.CharField(max_length=255)
    budget = models.DecimalField(max_digits=14, decimal_places=2)
    average_market_price = models.DecimalField(max_digits=14, decimal_places=2)
    final_price = models.DecimalField(max_digits=14, decimal_places=2)
    participants_count = models.PositiveIntegerField(default=0)
    participants = models.ManyToManyField(Company, blank=True, related_name='tenders')
    winner_company = models.ForeignKey(
        Company,
        related_name='won_tenders',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    is_completed_by_winner = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField()
    deadline = models.DateTimeField()
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        if self.deadline <= self.created_at:
            raise ValidationError({'deadline': 'Deadline must be later than created_at.'})

    def save(self, *args, **kwargs):
        if not self.external_id:
            year = self.created_at.year if self.created_at else 2024
            next_number = (Tender.objects.exclude(pk=self.pk).count() + 1)
            self.external_id = f'T-{year}-{next_number:04d}'
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    @admin.display(description='Price Difference %')
    def price_difference_percent(self) -> Decimal:
        if self.average_market_price in (None, ZERO_DECIMAL):
            return ZERO_DECIMAL
        difference = self.final_price - self.average_market_price
        return ((difference / self.average_market_price) * HUNDRED_DECIMAL).quantize(
            Decimal('0.01')
        )

    @property
    def budget_difference_percent(self) -> Decimal:
        if self.budget in (None, ZERO_DECIMAL):
            return ZERO_DECIMAL
        difference = self.final_price - self.budget
        return ((difference / self.budget) * HUNDRED_DECIMAL).quantize(Decimal('0.01'))

    def get_actual_participants_count(self) -> int:
        if self.pk:
            participants_total = self.participants.count()
            if participants_total:
                return participants_total
        return self.participants_count


class TenderRiskAnalysis(models.Model):
    class RiskLevel(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'

    tender = models.OneToOneField(
        Tender,
        on_delete=models.CASCADE,
        related_name='risk_analysis',
    )
    total_score = models.PositiveIntegerField(default=0)
    risk_level = models.CharField(
        max_length=10,
        choices=RiskLevel.choices,
        default=RiskLevel.LOW,
    )
    price_score = models.PositiveIntegerField(default=0)
    company_history_score = models.PositiveIntegerField(default=0)
    consecutive_wins_score = models.PositiveIntegerField(default=0)
    participants_score = models.PositiveIntegerField(default=0)
    fake_competition_score = models.PositiveIntegerField(default=0)
    ai_summary = models.TextField(blank=True, default='')
    analyzed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-analyzed_at']

    def __str__(self) -> str:
        return f'Risk analysis for {self.tender}'

    def calculate_total_score(self) -> int:
        self.total_score = min(
            self.price_score
            + self.company_history_score
            + self.consecutive_wins_score
            + self.participants_score
            + self.fake_competition_score,
            100,
        )
        return self.total_score

    def update_risk_level(self) -> str:
        if self.total_score >= 70:
            self.risk_level = self.RiskLevel.HIGH
        elif self.total_score >= 40:
            self.risk_level = self.RiskLevel.MEDIUM
        else:
            self.risk_level = self.RiskLevel.LOW
        return self.risk_level

    def save(self, *args, **kwargs):
        self.calculate_total_score()
        self.update_risk_level()
        super().save(*args, **kwargs)


class RiskReason(models.Model):
    analysis = models.ForeignKey(
        TenderRiskAnalysis,
        on_delete=models.CASCADE,
        related_name='reasons',
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    score = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return self.title


class TenderBid(models.Model):
    external_id = models.CharField(max_length=50, unique=True, blank=True, default='')
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='bids')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='bids')
    bid_price = models.DecimalField(max_digits=14, decimal_places=2)
    product_name = models.CharField(max_length=120, blank=True, default='')
    product_description = models.TextField(blank=True, default='')
    is_winner = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['tender', 'company'],
                name='unique_tender_company_bid',
            ),
        ]
        ordering = ['bid_price', 'id']

    def __str__(self) -> str:
        return f'{self.company} bid for {self.tender}'

    @property
    def status(self) -> str:
        if self.is_winner:
            return 'won'
        if self.tender.winner_company_id:
            return 'lost'
        return 'pending'

    def clean(self) -> None:
        if self.bid_price <= ZERO_DECIMAL:
            raise ValidationError({'bid_price': 'Bid price must be positive.'})

    def save(self, *args, **kwargs):
        if not self.external_id:
            self.external_id = f'A-{timezone_now_compact()}'
        self.full_clean()
        super().save(*args, **kwargs)


def timezone_now_compact() -> str:
    from django.utils import timezone

    return timezone.now().strftime('%Y%m%d%H%M%S%f')[-10:].upper()
