from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tenders.models import Company, Tender, TenderBid
from tenders.services.risk_scoring import analyze_all_companies


COMPANY_NAMES = [
    'Atlas Road Builders',
    'Blue River Supplies',
    'Capital Medical Systems',
    'CivicTech Solutions',
    'Eastern Logistics Group',
    'Evergreen Construction',
    'FutureGrid Energy',
    'Golden Valley Foods',
    'Harbor Safety Equipment',
    'Ipak Yoli Engineering',
    'Jade Procurement Group',
    'Kokand Civil Works',
    'Metro Signal Systems',
    'Navoi Industrial Supply',
    'Orion Water Services',
    'Prime Office Interiors',
    'Qibray Electrical',
    'Registan Data Systems',
    'Samarkand Bridge Works',
    'Silk Road Machinery',
    'Tashkent Facility Services',
    'Termez Medical Trade',
    'Turon Asphalt Company',
    'Urban Light Systems',
    'Valley Security Services',
    'Vertex Diagnostics',
    'White Stone Contractors',
    'Yuksalish Transport',
    'Zarafshan Agro Supply',
    'Zenith Public Works',
    'Apex Tender Partners',
    'BrightLine Infrastructure',
    'Delta Audit Supplies',
    'Emerald Hospital Systems',
    'Falcon Road Services',
    'Global Civic Materials',
]

COMPANY_PREFIXES = [
    'Atlas',
    'Blue River',
    'Capital',
    'Civic',
    'Eastern',
    'Evergreen',
    'FutureGrid',
    'Golden Valley',
    'Harbor',
    'Ipak Yoli',
    'Jade',
    'Kokand',
    'Metro',
    'Navoi',
    'Orion',
    'Prime',
    'Qibray',
    'Registan',
    'Samarkand',
    'Silk Road',
    'Tashkent',
    'Termez',
    'Turon',
    'Urban',
    'Valley',
    'Vertex',
    'White Stone',
    'Yuksalish',
    'Zarafshan',
    'Zenith',
]

COMPANY_SUFFIXES = [
    'Infrastructure',
    'Medical Trade',
    'Public Works',
    'Engineering',
    'Supply Group',
    'Facility Services',
    'Energy Systems',
    'Transport',
    'Diagnostics',
    'Civil Materials',
]

ORGANIZATIONS = [
    'City Infrastructure Office',
    'National Health Agency',
    'Ministry of Education',
    'Regional Water Authority',
    'Public Transport Department',
    'Digital Government Center',
    'Emergency Services Directorate',
    'Agriculture Support Agency',
    'Energy Modernization Office',
    'Municipal Housing Committee',
]

CATEGORIES = [
    'Road Works',
    'Medical Equipment',
    'School Supplies',
    'Water Infrastructure',
    'Public Transport',
    'IT Services',
    'Safety Equipment',
    'Agricultural Supplies',
    'Energy Systems',
    'Facility Maintenance',
]

PRODUCTS = {
    'Road Works': 'asphalt and road rehabilitation package',
    'Medical Equipment': 'diagnostic and hospital equipment bundle',
    'School Supplies': 'classroom furniture and learning materials',
    'Water Infrastructure': 'pump station and pipeline maintenance package',
    'Public Transport': 'bus depot equipment and spare parts',
    'IT Services': 'software support and hardware maintenance package',
    'Safety Equipment': 'protective equipment and emergency response kit',
    'Agricultural Supplies': 'greenhouse and irrigation supply package',
    'Energy Systems': 'substation equipment and lighting package',
    'Facility Maintenance': 'building repair and maintenance services',
}

BASELINES = {
    'Road Works': Decimal('420000.00'),
    'Medical Equipment': Decimal('310000.00'),
    'School Supplies': Decimal('95000.00'),
    'Water Infrastructure': Decimal('260000.00'),
    'Public Transport': Decimal('380000.00'),
    'IT Services': Decimal('140000.00'),
    'Safety Equipment': Decimal('85000.00'),
    'Agricultural Supplies': Decimal('125000.00'),
    'Energy Systems': Decimal('330000.00'),
    'Facility Maintenance': Decimal('76000.00'),
}

SUSPICIOUS_WINNERS = {
    'Atlas Road Builders',
    'Capital Medical Systems',
    'Apex Tender Partners',
    'Turon Asphalt Company',
}


def slugify(value: str) -> str:
    return ''.join(char.lower() if char.isalnum() else '-' for char in value).strip('-')


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'))


class Command(BaseCommand):
    help = 'Seed a larger deterministic presentation dataset with 100+ tenders and bids.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Delete the generated presentation dataset before recreating it.',
        )
        parser.add_argument(
            '--tenders',
            type=int,
            default=120,
            help='Number of presentation tenders to create. Default: 120.',
        )
        parser.add_argument(
            '--companies',
            type=int,
            default=100,
            help='Number of presentation companies to create. Default: 100.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tender_count = max(options['tenders'], 100)
        company_count = max(options['companies'], 100)

        if options['force']:
            Tender.objects.filter(external_id__startswith='T-PRESENT-').delete()
            Company.objects.filter(external_id__startswith='c-present-').delete()

        company_names = list(dict.fromkeys(COMPANY_NAMES))
        for prefix in COMPANY_PREFIXES:
            for suffix in COMPANY_SUFFIXES:
                company_names.append(f'{prefix} {suffix}')
                if len(company_names) >= company_count:
                    break
            if len(company_names) >= company_count:
                break

        companies = []
        for name in company_names[:company_count]:
            company, _ = Company.objects.update_or_create(
                external_id=f'c-present-{slugify(name)}',
                defaults={'name': name},
            )
            companies.append(company)

        now = timezone.now()
        created_tenders = []

        for index in range(1, tender_count + 1):
            category_index = (index - 1) % len(CATEGORIES)
            category = CATEGORIES[category_index]
            organization = ORGANIZATIONS[category_index]
            baseline = BASELINES[category]
            market_variation = Decimal((index % 9) - 4) / Decimal('100')
            average_market_price = money(baseline * (Decimal('1.00') + market_variation))
            budget = money(average_market_price * (Decimal('1.07') + Decimal(index % 5) / Decimal('100')))

            is_active = index % 5 == 0
            is_cancelled = index % 17 == 0
            created_at = now - timezone.timedelta(days=180 - index)
            deadline = created_at + timezone.timedelta(days=10 + (index % 12))
            if is_active:
                created_at = now - timezone.timedelta(days=index % 10)
                deadline = now + timezone.timedelta(days=7 + (index % 20))

            participant_count = 3 + (index % 4)
            participant_start = (index * 3) % len(companies)
            participants = [
                companies[(participant_start + offset) % len(companies)]
                for offset in range(participant_count)
            ]

            if index <= 22:
                winner = companies[0]
                participants = [winner, companies[1], companies[2], companies[3]]
                category = 'Road Works'
                organization = 'City Infrastructure Office'
                average_market_price = money(BASELINES[category] * Decimal('0.92'))
                budget = money(BASELINES[category] * Decimal('1.06'))
            elif 23 <= index <= 36:
                winner = companies[2]
                participants = [winner, companies[10], companies[15], companies[25]]
                category = 'Medical Equipment'
                organization = 'National Health Agency'
                average_market_price = money(BASELINES[category] * Decimal('0.88'))
                budget = money(BASELINES[category] * Decimal('1.08'))
            else:
                winner = participants[index % len(participants)]

            if is_active or is_cancelled:
                winner_company = None
                final_price = Decimal('0.00')
                is_completed_by_winner = None
                status = Tender.Status.ACTIVE if is_active else Tender.Status.CANCELLED
            else:
                winner_company = winner
                suspicious = winner.name in SUSPICIOUS_WINNERS or index % 19 == 0
                multiplier = Decimal('1.32') if suspicious else Decimal('0.94') + Decimal(index % 11) / Decimal('100')
                final_price = money(average_market_price * multiplier)
                is_completed_by_winner = not (suspicious and index % 3 == 0)
                status = Tender.Status.COMPLETED

            tender, _ = Tender.objects.update_or_create(
                external_id=f'T-PRESENT-{index:04d}',
                defaults={
                    'title': f'{organization} {category} Tender {index:03d}',
                    'organization': organization,
                    'category': category,
                    'budget': budget,
                    'average_market_price': average_market_price,
                    'final_price': final_price,
                    'participants_count': len(participants),
                    'winner_company': winner_company,
                    'status': status,
                    'is_completed_by_winner': is_completed_by_winner,
                    'created_at': created_at,
                    'deadline': deadline,
                },
            )
            tender.participants.set(participants)
            tender.bids.all().delete()

            if final_price > 0:
                winning_price = final_price
            else:
                winning_price = money(average_market_price * (Decimal('0.92') + Decimal(index % 9) / Decimal('100')))

            for bid_index, company in enumerate(participants):
                is_winner = bool(winner_company and company.id == winner_company.id)
                if is_winner:
                    bid_price = winning_price
                elif winner_company and winner_company.name in SUSPICIOUS_WINNERS and index <= 36:
                    bid_price = money(winning_price * (Decimal('1.010') + Decimal(bid_index) / Decimal('1000')))
                else:
                    bid_price = money(winning_price * (Decimal('1.03') + Decimal(bid_index + 1) / Decimal('100')))

                TenderBid.objects.create(
                    tender=tender,
                    company=company,
                    bid_price=bid_price,
                    product_name=f'{category} package {index:03d}-{bid_index + 1}',
                    product_description=(
                        f'Proposal for {PRODUCTS[category]} submitted by {company.name}.'
                    ),
                    is_winner=is_winner,
                )

            created_tenders.append(tender)

        analyze_all_companies()

        self.stdout.write(
            self.style.SUCCESS(
                'Presentation data ready: '
                f'{len(companies)} companies, {len(created_tenders)} tenders, '
                f'{TenderBid.objects.filter(tender__external_id__startswith="T-PRESENT-").count()} bids.'
            )
        )
