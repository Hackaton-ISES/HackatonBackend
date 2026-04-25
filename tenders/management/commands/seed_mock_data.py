from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from tenders.models import Company, Tender


class Command(BaseCommand):
    help = 'Seed the database with mock tender and company data for MVP testing.'

    def handle(self, *args, **options):
        if Tender.objects.exists() or Company.objects.exists():
            self.stdout.write(self.style.WARNING('Mock data already exists. Skipping seed.'))
            return

        companies = {
            'Reliable Builders': Company.objects.create(
                name='Reliable Builders',
                total_participations=12,
                total_wins=9,
            ),
            'Fair Price Engineering': Company.objects.create(
                name='Fair Price Engineering',
                total_participations=7,
                total_wins=2,
            ),
            'Always Losing LLC': Company.objects.create(
                name='Always Losing LLC',
                total_participations=8,
                total_wins=0,
            ),
            'Solo Bid Supplies': Company.objects.create(
                name='Solo Bid Supplies',
                total_participations=3,
                total_wins=1,
            ),
        }

        now = timezone.now()
        tenders = [
            {
                'title': 'Regional Hospital Renovation',
                'organization': 'Ministry of Health',
                'category': 'Construction',
                'budget': Decimal('150000.00'),
                'average_market_price': Decimal('100000.00'),
                'final_price': Decimal('148000.00'),
                'status': Tender.Status.COMPLETED,
                'is_completed_by_winner': True,
                'created_at': now - timezone.timedelta(days=2),
                'deadline': now - timezone.timedelta(days=1),
                'winner_company': companies['Reliable Builders'],
                'participants': [
                    companies['Reliable Builders'],
                    companies['Always Losing LLC'],
                ],
            },
            {
                'title': 'Municipal IT Hardware Purchase',
                'organization': 'City Procurement Office',
                'category': 'IT Equipment',
                'budget': Decimal('50000.00'),
                'average_market_price': Decimal('47000.00'),
                'final_price': Decimal('48000.00'),
                'status': Tender.Status.COMPLETED,
                'is_completed_by_winner': True,
                'created_at': now - timezone.timedelta(days=10),
                'deadline': now - timezone.timedelta(days=5),
                'winner_company': companies['Fair Price Engineering'],
                'participants': [
                    companies['Fair Price Engineering'],
                    companies['Always Losing LLC'],
                ],
            },
            {
                'title': 'Emergency Water Pump Delivery',
                'organization': 'Regional Utilities Agency',
                'category': 'Utilities',
                'budget': Decimal('75000.00'),
                'average_market_price': Decimal('50000.00'),
                'final_price': Decimal('74000.00'),
                'status': Tender.Status.ACTIVE,
                'is_completed_by_winner': None,
                'created_at': now - timezone.timedelta(days=1),
                'deadline': now + timezone.timedelta(hours=36),
                'winner_company': companies['Solo Bid Supplies'],
                'participants': [companies['Solo Bid Supplies']],
            },
        ]

        for item in tenders:
            participants = item.pop('participants')
            tender = Tender.objects.create(
                participants_count=len(participants),
                **item,
            )
            tender.participants.set(participants)

        self.stdout.write(self.style.SUCCESS('Mock data seeded successfully.'))
