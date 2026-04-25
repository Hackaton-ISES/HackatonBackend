from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from tenders.models import Company, Tender, TenderBid, UserProfile
from tenders.services.risk_scoring import analyze_tender


class Command(BaseCommand):
    help = 'Seed the database with realistic mock data and demo users for Tender Guardian.'

    def handle(self, *args, **options):
        if Tender.objects.exists() or Company.objects.exists() or User.objects.exists():
            self.stdout.write(self.style.WARNING('Mock data already exists. Skipping seed.'))
            return

        admin_user = User.objects.create_superuser(
            username='admin',
            password='admin123',
            email='admin@tender-guardian.local',
            first_name='System',
            last_name='Admin',
        )
        UserProfile.objects.create(
            user=admin_user,
            role=UserProfile.Role.ADMIN,
            external_id='u-admin',
        )

        companies = {
            'Acme Corp': Company.objects.create(
                external_id='c-acme',
                name='Acme Corp',
                total_participations=10,
                total_wins=3,
                completed_projects=3,
                failed_projects=0,
            ),
            'Nova Solutions': Company.objects.create(
                external_id='c-nova',
                name='Nova Solutions',
                total_participations=11,
                total_wins=2,
                completed_projects=1,
                failed_projects=1,
            ),
            'Alpha Infrastructure': Company.objects.create(
                name='Alpha Infrastructure',
                total_participations=15,
                total_wins=7,
                completed_projects=6,
                failed_projects=1,
            ),
            'Beta Civil Works': Company.objects.create(
                name='Beta Civil Works',
                total_participations=14,
                total_wins=1,
                completed_projects=1,
                failed_projects=0,
            ),
            'Gamma Procurement': Company.objects.create(
                name='Gamma Procurement',
                total_participations=14,
                total_wins=1,
                completed_projects=1,
                failed_projects=0,
            ),
            'Delta Supplies': Company.objects.create(
                name='Delta Supplies',
                total_participations=13,
                total_wins=1,
                completed_projects=1,
                failed_projects=0,
            ),
        }

        acme_user = User.objects.create_user(
            username='acme',
            password='acme123',
            email='acme@tender-guardian.local',
        )
        UserProfile.objects.create(
            user=acme_user,
            role=UserProfile.Role.COMPANY,
            company=companies['Acme Corp'],
            external_id='c-acme',
        )

        nova_user = User.objects.create_user(
            username='nova',
            password='nova123',
            email='nova@tender-guardian.local',
        )
        UserProfile.objects.create(
            user=nova_user,
            role=UserProfile.Role.COMPANY,
            company=companies['Nova Solutions'],
            external_id='c-nova',
        )

        now = timezone.now()

        def create_tender(*, participants, bids=None, late_bid_company=None, analyze=True, **kwargs):
            tender = Tender.objects.create(participants_count=len(participants), **kwargs)
            tender.participants.set(participants)
            for company in participants:
                company.update_statistics()
            for bid in bids or []:
                created_bid = TenderBid.objects.create(tender=tender, **bid)
                if late_bid_company and created_bid.company == late_bid_company:
                    TenderBid.objects.filter(pk=created_bid.pk).update(
                        created_at=tender.deadline + timezone.timedelta(hours=2)
                    )
            if tender.winner_company:
                tender.winner_company.update_statistics()
            if analyze:
                analyze_tender(tender)
            return tender

        create_tender(
            title='Routine Office Furniture Supply',
            organization='Central Administration',
            category='Office Supplies',
            budget=Decimal('100000.00'),
            average_market_price=Decimal('95000.00'),
            final_price=Decimal('98000.00'),
            status=Tender.Status.COMPLETED,
            is_completed_by_winner=True,
            created_at=now - timezone.timedelta(days=35),
            deadline=now - timezone.timedelta(days=30),
            winner_company=companies['Acme Corp'],
            participants=[companies['Acme Corp'], companies['Delta Supplies']],
            bids=[
                {
                    'company': companies['Acme Corp'],
                    'bid_price': Decimal('98000.00'),
                    'is_winner': True,
                    'product_name': 'Office desks',
                    'product_description': 'Ergonomic office furniture package',
                },
                {'company': companies['Delta Supplies'], 'bid_price': Decimal('103000.00'), 'is_winner': False},
            ],
        )

        create_tender(
            title='Hospital Imaging Device Purchase',
            organization='National Health Agency',
            category='Medical Equipment',
            budget=Decimal('250000.00'),
            average_market_price=Decimal('180000.00'),
            final_price=Decimal('275000.00'),
            status=Tender.Status.COMPLETED,
            is_completed_by_winner=False,
            created_at=now - timezone.timedelta(days=28),
            deadline=now - timezone.timedelta(days=24),
            winner_company=companies['Nova Solutions'],
            participants=[companies['Nova Solutions'], companies['Gamma Procurement']],
            bids=[
                {
                    'company': companies['Nova Solutions'],
                    'bid_price': Decimal('275000.00'),
                    'is_winner': True,
                    'product_name': 'Imaging devices',
                    'product_description': 'MRI and CT procurement bundle',
                },
                {'company': companies['Gamma Procurement'], 'bid_price': Decimal('279000.00'), 'is_winner': False},
            ],
        )

        for offset in range(4):
            create_tender(
                title=f'Road Rehabilitation Package {offset + 1}',
                organization='City Infrastructure Office',
                category='Road Works',
                budget=Decimal('400000.00'),
                average_market_price=Decimal('360000.00'),
                final_price=Decimal('365000.00') + Decimal(offset * 1000),
                status=Tender.Status.COMPLETED,
                is_completed_by_winner=True,
                created_at=now - timezone.timedelta(days=20 - offset),
                deadline=now - timezone.timedelta(days=17 - offset),
                winner_company=companies['Alpha Infrastructure'],
                participants=[
                    companies['Alpha Infrastructure'],
                    companies['Beta Civil Works'],
                    companies['Gamma Procurement'],
                    companies['Delta Supplies'],
                ],
                bids=[
                    {'company': companies['Alpha Infrastructure'], 'bid_price': Decimal('365000.00') + Decimal(offset * 1000), 'is_winner': True},
                    {'company': companies['Beta Civil Works'], 'bid_price': Decimal('369500.00') + Decimal(offset * 1000), 'is_winner': False},
                    {'company': companies['Gamma Procurement'], 'bid_price': Decimal('370200.00') + Decimal(offset * 1000), 'is_winner': False},
                    {'company': companies['Delta Supplies'], 'bid_price': Decimal('371000.00') + Decimal(offset * 1000), 'is_winner': False},
                ],
            )

        create_tender(
            title='Road Rehabilitation Package 5',
            organization='City Infrastructure Office',
            category='Road Works',
            budget=Decimal('382000.00'),
            average_market_price=Decimal('330000.00'),
            final_price=Decimal('382000.00'),
            status=Tender.Status.COMPLETED,
            is_completed_by_winner=True,
            created_at=now - timezone.timedelta(days=10),
            deadline=now - timezone.timedelta(days=8),
            winner_company=companies['Alpha Infrastructure'],
            participants=[
                companies['Alpha Infrastructure'],
                companies['Beta Civil Works'],
                companies['Gamma Procurement'],
                companies['Delta Supplies'],
            ],
            bids=[
                {'company': companies['Alpha Infrastructure'], 'bid_price': Decimal('382000.00'), 'is_winner': True},
                {'company': companies['Beta Civil Works'], 'bid_price': Decimal('387500.00'), 'is_winner': False},
                {'company': companies['Gamma Procurement'], 'bid_price': Decimal('388000.00'), 'is_winner': False},
                {'company': companies['Delta Supplies'], 'bid_price': Decimal('389200.00'), 'is_winner': False},
            ],
            late_bid_company=companies['Delta Supplies'],
        )

        self.stdout.write(self.style.SUCCESS('Mock data seeded successfully.'))
