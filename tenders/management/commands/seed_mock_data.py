from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from tenders.models import Company, Tender, TenderBid, UserProfile
from tenders.services.risk_scoring import analyze_all_companies


DEMO_USERNAMES = ['admin', 'acme', 'nova']
DEMO_COMPANIES = {
    'c-acme': 'Acme Corp',
    'c-nova': 'Nova Solutions',
    'c-alpha-infrastructure': 'Alpha Infrastructure',
    'c-beta-civil-works': 'Beta Civil Works',
    'c-gamma-procurement': 'Gamma Procurement',
    'c-delta-supplies': 'Delta Supplies',
}
DEMO_TENDER_EXTERNAL_IDS = [
    'T-DEMO-0001',
    'T-DEMO-0002',
    'T-DEMO-0003',
    'T-DEMO-0004',
    'T-DEMO-0005',
    'T-DEMO-0006',
    'T-DEMO-0007',
]


class Command(BaseCommand):
    help = 'Seed the database with realistic mock data and demo users for Tender Guardian.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Delete existing demo data and seed again.',
        )

    def handle(self, *args, **options):
        if options['force']:
            Tender.objects.filter(external_id__in=DEMO_TENDER_EXTERNAL_IDS).delete()
            UserProfile.objects.filter(user__username__in=DEMO_USERNAMES).delete()
            User.objects.filter(username__in=DEMO_USERNAMES).delete()
            Company.objects.filter(external_id__in=list(DEMO_COMPANIES.keys())).delete()

        existing_demo_tenders = Tender.objects.filter(
            external_id__in=DEMO_TENDER_EXTERNAL_IDS
        ).count()
        existing_demo_companies = Company.objects.filter(
            external_id__in=list(DEMO_COMPANIES.keys())
        ).count()
        existing_demo_users = User.objects.filter(username__in=DEMO_USERNAMES).count()

        if existing_demo_tenders or existing_demo_companies or existing_demo_users:
            self.stdout.write(
                self.style.WARNING(
                    'Existing demo data detected. The command will update demo records in place.'
                )
            )
        else:
            self.stdout.write('No existing demo dataset found. Creating demo records.')

        admin_user, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@tender-guardian.local',
                'first_name': 'System',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        admin_user.email = 'admin@tender-guardian.local'
        admin_user.first_name = 'System'
        admin_user.last_name = 'Admin'
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.set_password('admin123')
        admin_user.save()
        UserProfile.objects.update_or_create(
            user=admin_user,
            defaults={
                'role': UserProfile.Role.ADMIN,
                'external_id': 'u-admin',
                'company': None,
            },
        )

        companies = {
            'Acme Corp': Company.objects.update_or_create(
                external_id='c-acme',
                defaults={
                    'name': 'Acme Corp',
                    'total_participations': 10,
                    'total_wins': 3,
                    'completed_projects': 3,
                    'failed_projects': 0,
                },
            )[0],
            'Nova Solutions': Company.objects.update_or_create(
                external_id='c-nova',
                defaults={
                    'name': 'Nova Solutions',
                    'total_participations': 11,
                    'total_wins': 2,
                    'completed_projects': 1,
                    'failed_projects': 1,
                },
            )[0],
            'Alpha Infrastructure': Company.objects.update_or_create(
                external_id='c-alpha-infrastructure',
                defaults={
                    'name': 'Alpha Infrastructure',
                    'total_participations': 15,
                    'total_wins': 7,
                    'completed_projects': 6,
                    'failed_projects': 1,
                },
            )[0],
            'Beta Civil Works': Company.objects.update_or_create(
                external_id='c-beta-civil-works',
                defaults={
                    'name': 'Beta Civil Works',
                    'total_participations': 14,
                    'total_wins': 1,
                    'completed_projects': 1,
                    'failed_projects': 0,
                },
            )[0],
            'Gamma Procurement': Company.objects.update_or_create(
                external_id='c-gamma-procurement',
                defaults={
                    'name': 'Gamma Procurement',
                    'total_participations': 14,
                    'total_wins': 1,
                    'completed_projects': 1,
                    'failed_projects': 0,
                },
            )[0],
            'Delta Supplies': Company.objects.update_or_create(
                external_id='c-delta-supplies',
                defaults={
                    'name': 'Delta Supplies',
                    'total_participations': 13,
                    'total_wins': 1,
                    'completed_projects': 1,
                    'failed_projects': 0,
                },
            )[0],
        }

        acme_user, _ = User.objects.get_or_create(
            username='acme',
            defaults={'email': 'acme@tender-guardian.local'},
        )
        acme_user.email = 'acme@tender-guardian.local'
        acme_user.set_password('acme123')
        acme_user.save()
        UserProfile.objects.update_or_create(
            user=acme_user,
            defaults={
                'role': UserProfile.Role.COMPANY,
                'company': companies['Acme Corp'],
                'external_id': 'c-acme',
            },
        )

        nova_user, _ = User.objects.get_or_create(
            username='nova',
            defaults={'email': 'nova@tender-guardian.local'},
        )
        nova_user.email = 'nova@tender-guardian.local'
        nova_user.set_password('nova123')
        nova_user.save()
        UserProfile.objects.update_or_create(
            user=nova_user,
            defaults={
                'role': UserProfile.Role.COMPANY,
                'company': companies['Nova Solutions'],
                'external_id': 'c-nova',
            },
        )

        now = timezone.now()

        def create_tender(
            *, external_id, participants, bids=None, late_bid_company=None, **kwargs
        ):
            tender, _ = Tender.objects.update_or_create(
                external_id=external_id,
                defaults={'participants_count': len(participants), **kwargs},
            )
            tender.participants.set(participants)
            tender.bids.all().delete()
            for company in participants:
                company.update_statistics()
            for bid in bids or []:
                created_bid = TenderBid.objects.create(tender=tender, **bid)
                if late_bid_company and created_bid.company == late_bid_company:
                    TenderBid.objects.filter(pk=created_bid.pk).update(
                        created_at=tender.deadline + timezone.timedelta(hours=2)
                    )
            return tender

        create_tender(
            external_id='T-DEMO-0001',
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
            external_id='T-DEMO-0002',
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
                external_id=f'T-DEMO-000{offset + 3}',
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
            external_id='T-DEMO-0007',
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

        analyze_all_companies()

        self.stdout.write(
            self.style.SUCCESS(
                'Mock data seeded successfully. Demo users: admin/admin123, acme/acme123, nova/nova123.'
            )
        )
