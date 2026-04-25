from decimal import Decimal

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from tenders.models import Company, Tender
from tenders.services.risk_analysis import RiskLevel, analyze_tender_risk


class RiskAnalysisServiceTests(APITestCase):
    def test_analyze_tender_risk_returns_high_risk_for_multiple_red_flags(self):
        winner = Company.objects.create(
            name='Dominant Supplier',
            total_participations=10,
            total_wins=8,
        )
        repeated_loser = Company.objects.create(
            name='Always Losing LLC',
            total_participations=8,
            total_wins=0,
        )
        now = timezone.now()
        tender = Tender.objects.create(
            title='Medical Equipment Procurement',
            organization='Health Ministry',
            budget=Decimal('100000.00'),
            average_market_price=Decimal('70000.00'),
            final_price=Decimal('98000.00'),
            participants_count=2,
            winner_company=winner,
            created_at=now,
            deadline=now + timezone.timedelta(days=1),
        )
        tender.participants.set([winner, repeated_loser])

        result = analyze_tender_risk(tender)

        self.assertGreaterEqual(result.risk_score, 85)
        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertTrue(any('Repeated loser pattern' in reason for reason in result.reasons))


class TenderApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_mock_data')

    def test_get_tenders_returns_analysis_payload(self):
        response = self.client.get(reverse('tender-list-create'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertIn('risk_score', response.data[0])
        self.assertIn('risk_level', response.data[0])
        self.assertIn('reasons', response.data[0])

    def test_get_tender_detail_returns_analysis_payload(self):
        tender = Tender.objects.first()

        response = self.client.get(reverse('tender-detail', args=[tender.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], tender.id)
        self.assertIn('risk_score', response.data)

    def test_post_tender_creates_tender_and_updates_company_stats(self):
        company_one = Company.objects.create(
            name='New Bidder One',
            total_participations=2,
            total_wins=0,
        )
        company_two = Company.objects.create(
            name='New Bidder Two',
            total_participations=4,
            total_wins=1,
        )
        payload = {
            'title': 'Road Repair Contract',
            'organization': 'City Council',
            'budget': '200000.00',
            'average_market_price': '140000.00',
            'final_price': '195000.00',
            'participant_ids': [company_one.id, company_two.id],
            'winner_company_id': company_two.id,
            'created_at': '2026-04-20T10:00:00Z',
            'deadline': '2026-04-21T10:00:00Z',
        }

        response = self.client.post(reverse('tender-list-create'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['participants_count'], 2)
        company_one.refresh_from_db()
        company_two.refresh_from_db()
        self.assertEqual(company_one.total_participations, 3)
        self.assertEqual(company_two.total_participations, 5)
        self.assertEqual(company_two.total_wins, 2)

# Create your tests here.
