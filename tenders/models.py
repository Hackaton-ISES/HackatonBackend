from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import models


ZERO_DECIMAL = Decimal('0')
HUNDRED_DECIMAL = Decimal('100')


class Company(models.Model):
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

    @property
    @admin.display(description='Failure Rate')
    def failure_rate(self) -> Decimal:
        if self.total_wins == 0:
            return ZERO_DECIMAL
        return ((Decimal(self.failed_projects) / Decimal(self.total_wins)) * HUNDRED_DECIMAL).quantize(
            Decimal('0.01')
        )

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


class Tender(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

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

    def get_actual_participants_count(self) -> int:
        if self.pk and hasattr(self, 'participants'):
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
    analyzed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-analyzed_at']

    def __str__(self) -> str:
        return f'Risk analysis for {self.tender}'

    def calculate_price_score(self) -> int:
        difference_percent = self.tender.price_difference_percent
        if difference_percent < Decimal('10'):
            return 0
        if difference_percent < Decimal('20'):
            return 10
        if difference_percent < Decimal('35'):
            return 20
        if difference_percent < Decimal('50'):
            return 30
        return 40

    def calculate_company_history_score(self) -> int:
        winner = self.tender.winner_company
        if winner is None:
            return 0
        if winner.total_wins == 0:
            return 30 if winner.failed_projects > 0 else 0

        failure_ratio = (
            Decimal(winner.failed_projects) / Decimal(winner.total_wins)
        ) * HUNDRED_DECIMAL

        if failure_ratio < Decimal('10'):
            return 0
        if failure_ratio < Decimal('30'):
            return 10
        if failure_ratio < Decimal('50'):
            return 20
        return 30

    def calculate_consecutive_wins_count(self) -> int:
        tender = self.tender
        if tender.winner_company_id is None:
            return 0

        matching_tenders = (
            Tender.objects.filter(
                organization=tender.organization,
                category=tender.category,
                created_at__lte=tender.created_at,
            )
            .exclude(status=Tender.Status.CANCELLED)
            .select_related('winner_company')
            .order_by('created_at', 'id')
        )

        consecutive_count = 0
        current_streak = 0
        previous_winner_id = None

        for item in matching_tenders:
            if item.winner_company_id and item.winner_company_id == previous_winner_id:
                current_streak += 1
            elif item.winner_company_id:
                current_streak = 1
            else:
                current_streak = 0

            previous_winner_id = item.winner_company_id

            if item.pk == tender.pk:
                consecutive_count = (
                    current_streak if item.winner_company_id == tender.winner_company_id else 0
                )
                break

        return consecutive_count

    def calculate_consecutive_wins_score(self) -> int:
        wins_count = self.calculate_consecutive_wins_count()
        if wins_count <= 2:
            return 0
        if wins_count == 3:
            return 10
        if wins_count == 4:
            return 20
        return 30

    def calculate_participants_score(self) -> int:
        return 20 if self.tender.get_actual_participants_count() <= 1 else 0

    def calculate_total_score(self) -> int:
        self.price_score = self.calculate_price_score()
        self.company_history_score = self.calculate_company_history_score()
        self.consecutive_wins_score = self.calculate_consecutive_wins_score()
        self.participants_score = self.calculate_participants_score()
        return min(
            self.price_score
            + self.company_history_score
            + self.consecutive_wins_score
            + self.participants_score,
            100,
        )

    def update_risk_level(self) -> str:
        if self.total_score >= 70:
            self.risk_level = self.RiskLevel.HIGH
        elif self.total_score >= 40:
            self.risk_level = self.RiskLevel.MEDIUM
        else:
            self.risk_level = self.RiskLevel.LOW
        return self.risk_level

    def save(self, *args, **kwargs):
        self.total_score = self.calculate_total_score()
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
