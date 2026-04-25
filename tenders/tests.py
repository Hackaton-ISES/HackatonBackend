from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from tenders.models import Company, Tender, TenderBid, TenderRiskAnalysis, UserProfile
from tenders.services.risk_scoring import (
    analyze_tender,
    calculate_company_history_score,
    calculate_consecutive_wins_score,
    calculate_fake_competition_score,
    calculate_participants_score,
    calculate_price_score,
)


class RiskScoringServiceTests(APITestCase):
    def setUp(self):
        self.now = timezone.now()
        self.winner = Company.objects.create(
            name='Winner Co',
            total_participations=10,
            total_wins=8,
            completed_projects=4,
            failed_projects=4,
        )
        self.loser_one = Company.objects.create(name='Loser One')
        self.loser_two = Company.objects.create(name='Loser Two')
        self.loser_three = Company.objects.create(name='Loser Three')

    def _create_tender(self, **overrides):
        values = {
            'title': 'Test Tender',
            'organization': 'Transport Agency',
            'category': 'Road Works',
            'budget': Decimal('100000.00'),
            'average_market_price': Decimal('80000.00'),
            'final_price': Decimal('98000.00'),
            'participants_count': 4,
            'winner_company': self.winner,
            'status': Tender.Status.COMPLETED,
            'is_completed_by_winner': True,
            'created_at': self.now,
            'deadline': self.now + timezone.timedelta(days=5),
        }
        values.update(overrides)
        tender = Tender.objects.create(**values)
        tender.participants.set([self.winner, self.loser_one, self.loser_two, self.loser_three])
        return tender

    def test_price_score_calculation(self):
        tender = self._create_tender(final_price=Decimal('100000.00'))
        result = calculate_price_score(tender)
        self.assertGreaterEqual(result.score, 20)
        self.assertTrue(any(reason.title == 'Price comparison risk' for reason in result.reasons))

    def test_company_history_score_calculation(self):
        tender = self._create_tender()
        result = calculate_company_history_score(tender)
        self.assertEqual(result.score, 20)

    def test_consecutive_wins_score_calculation(self):
        for index in range(2):
            self._create_tender(
                title=f'Past {index}',
                created_at=self.now - timezone.timedelta(days=4 - index),
                deadline=self.now - timezone.timedelta(days=2 - index),
            )
        current = self._create_tender(title='Current Consecutive')
        result = calculate_consecutive_wins_score(current)
        self.assertGreaterEqual(result.score, 10)

    def test_fake_competition_score_calculation(self):
        for index in range(4):
            previous = self._create_tender(
                title=f'Pattern {index}',
                created_at=self.now - timezone.timedelta(days=10 - index),
                deadline=self.now - timezone.timedelta(days=8 - index),
            )
            TenderBid.objects.create(tender=previous, company=self.winner, bid_price=Decimal('100000.00') + Decimal(index), is_winner=True)
            TenderBid.objects.create(tender=previous, company=self.loser_one, bid_price=Decimal('101000.00') + Decimal(index), is_winner=False)
            TenderBid.objects.create(tender=previous, company=self.loser_two, bid_price=Decimal('101500.00') + Decimal(index), is_winner=False)
            TenderBid.objects.create(tender=previous, company=self.loser_three, bid_price=Decimal('101800.00') + Decimal(index), is_winner=False)

        tender = self._create_tender(title='Collusion Candidate')
        TenderBid.objects.create(tender=tender, company=self.winner, bid_price=Decimal('120000.00'), is_winner=True)
        TenderBid.objects.create(tender=tender, company=self.loser_one, bid_price=Decimal('121500.00'), is_winner=False)
        TenderBid.objects.create(tender=tender, company=self.loser_two, bid_price=Decimal('122000.00'), is_winner=False)
        TenderBid.objects.create(tender=tender, company=self.loser_three, bid_price=Decimal('122300.00'), is_winner=False)

        result = calculate_fake_competition_score(tender)
        self.assertGreaterEqual(result.score, 45)

    def test_participants_score_calculation(self):
        tender = Tender.objects.create(
            title='Single Bidder',
            organization='Health Agency',
            category='Medical',
            budget=Decimal('1000.00'),
            average_market_price=Decimal('900.00'),
            final_price=Decimal('1000.00'),
            participants_count=1,
            winner_company=self.winner,
            status=Tender.Status.ACTIVE,
            created_at=self.now,
            deadline=self.now + timezone.timedelta(days=1),
        )
        tender.participants.set([self.winner])
        result = calculate_participants_score(tender)
        self.assertGreaterEqual(result.score, 25)

    def test_analyze_tender_creates_risk_analysis_and_reasons(self):
        tender = self._create_tender()
        TenderBid.objects.create(tender=tender, company=self.winner, bid_price=Decimal('95000.00'), is_winner=True)
        TenderBid.objects.create(tender=tender, company=self.loser_one, bid_price=Decimal('96000.00'), is_winner=False)
        TenderBid.objects.create(tender=tender, company=self.loser_two, bid_price=Decimal('96800.00'), is_winner=False)

        analysis = analyze_tender(tender)
        self.assertIsInstance(analysis, TenderRiskAnalysis)
        self.assertGreater(analysis.reasons.count(), 0)

    def test_total_score_is_capped_at_100(self):
        for index in range(6):
            previous = self._create_tender(
                title=f'Cap Pattern {index}',
                created_at=self.now - timezone.timedelta(days=20 - index),
                deadline=self.now - timezone.timedelta(days=18 - index),
                budget=Decimal('50000.00'),
                average_market_price=Decimal('50000.00'),
                final_price=Decimal('90000.00'),
            )
            TenderBid.objects.create(tender=previous, company=self.winner, bid_price=Decimal('90000.00'), is_winner=True)
            TenderBid.objects.create(tender=previous, company=self.loser_one, bid_price=Decimal('91000.00'), is_winner=False)
            TenderBid.objects.create(tender=previous, company=self.loser_two, bid_price=Decimal('91800.00'), is_winner=False)
            TenderBid.objects.create(tender=previous, company=self.loser_three, bid_price=Decimal('91900.00'), is_winner=False)

        tender = self._create_tender(
            title='Cap Target',
            budget=Decimal('50000.00'),
            average_market_price=Decimal('50000.00'),
            final_price=Decimal('90000.00'),
            deadline=self.now + timezone.timedelta(days=1),
        )
        TenderBid.objects.create(tender=tender, company=self.winner, bid_price=Decimal('90000.00'), is_winner=True)
        TenderBid.objects.create(tender=tender, company=self.loser_one, bid_price=Decimal('91000.00'), is_winner=False)
        TenderBid.objects.create(tender=tender, company=self.loser_two, bid_price=Decimal('91800.00'), is_winner=False)
        TenderBid.objects.create(tender=tender, company=self.loser_three, bid_price=Decimal('91900.00'), is_winner=False)

        analysis = analyze_tender(tender)
        self.assertEqual(analysis.total_score, 100)


class ApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_mock_data')
        cls.admin_user = User.objects.get(username='admin')
        cls.admin_token, _ = Token.objects.get_or_create(user=cls.admin_user)
        cls.company_user = User.objects.get(username='acme')
        cls.company_token, _ = Token.objects.get_or_create(user=cls.company_user)

    def test_auth_login_and_me(self):
        response = self.client.post(reverse('auth-login'), {'login': 'ADMIN', 'password': 'admin123'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['id'], 'u-admin')
        self.assertEqual(response.data['user']['login'], 'admin')
        self.assertEqual(response.data['user']['role'], 'admin')
        token = response.data['token']
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        me = self.client.get(reverse('auth-me'))
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data['id'], 'u-admin')
        self.assertEqual(me.data['name'], 'System Admin')

    def test_users_register_company(self):
        response = self.client.post(
            reverse('users-list-create'),
            {
                'username': 'new-company-user',
                'password': 'strongpass123',
                'company_name': 'New Company LLC',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Company.objects.filter(name='New Company LLC').exists())

    def test_tender_list_requires_auth(self):
        response = self.client.get(reverse('tender-list-create'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_tenders_returns_analysis_payload(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        response = self.client.get(reverse('tender-list-create'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('riskScore', response.data[0])
        self.assertIn('riskLevel', response.data[0])
        self.assertIn('riskFlags', response.data[0])

    def test_admin_can_create_tender_without_participants(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        response = self.client.post(
            reverse('tender-list-create'),
            {
                'title': 'New Open Tender',
                'organization': 'Education Board',
                'category': 'Supplies',
                'budget': '50000.00',
                'average_market_price': '47000.00',
                'final_price': '0.00',
                'created_at': timezone.now().isoformat().replace('+00:00', 'Z'),
                'deadline': (timezone.now() + timezone.timedelta(days=5)).isoformat().replace('+00:00', 'Z'),
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tender = Tender.objects.get(title='New Open Tender')
        self.assertEqual(tender.participants.count(), 0)
        self.assertEqual(tender.participants_count, 0)
        self.assertEqual(tender.status, Tender.Status.ACTIVE)
        self.assertIsNone(tender.is_completed_by_winner)

    def test_company_can_create_application(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.company_token.key}')
        tender = Tender.objects.create(
            title='Open Tender',
            organization='Utilities Agency',
            category='Supplies',
            budget=Decimal('100000.00'),
            average_market_price=Decimal('95000.00'),
            final_price=Decimal('0.00'),
            participants_count=0,
            status=Tender.Status.ACTIVE,
            created_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=3),
        )
        tender.external_id = 'T-2024-9999'
        tender.save(update_fields=['external_id'])
        response = self.client.post(
            reverse('applications-list-create'),
            {
                'tenderId': 'T-2024-9999',
                'companyId': 'c-acme',
                'companyName': 'Acme Corp',
                'proposedPrice': '99000.00',
                'productName': 'Emergency pumps',
                'productDescription': 'Industrial water pumps for urgent replacement',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['companyId'], 'c-acme')
        self.assertEqual(response.data['status'], 'Pending')

    def test_admin_can_patch_application_status(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        bid = TenderBid.objects.filter(is_winner=False).first()
        response = self.client.patch(
            reverse('application-status', args=[bid.external_id]),
            {'status': 'won'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bid.refresh_from_db()
        self.assertTrue(bid.is_winner)
        self.assertEqual(response.data['status'], 'Won')

    def test_risk_endpoint_returns_analysis(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        tender = Tender.objects.get(title='Road Rehabilitation Package 5')
        response = self.client.post(reverse('risk-analyze', args=[tender.external_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('totalScore', response.data)
        self.assertIn('riskFlags', response.data)

    def test_risk_flags_endpoint_returns_reasons(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        tender = Tender.objects.get(title='Road Rehabilitation Package 5')
        response = self.client.get(reverse('risk-flags', args=[tender.external_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertIn('severity', response.data[0])
        self.assertIn('message', response.data[0])

    def test_risk_stats_endpoint_returns_distribution(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        response = self.client.get(reverse('risk-stats'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('total', response.data)
        self.assertIn('high', response.data)
        self.assertIn('medium', response.data)
        self.assertIn('low', response.data)
        self.assertIn('distribution', response.data)

    def test_admin_can_update_and_delete_tender(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        tender = Tender.objects.first()
        update = self.client.put(
            reverse('tender-detail', args=[tender.external_id]),
            {
                'title': tender.title,
                'organization': tender.organization,
                'category': tender.category,
                'budget': str(tender.budget),
                'average_market_price': str(tender.average_market_price),
                'final_price': str(tender.final_price),
                'participant_ids': list(tender.participants.values_list('id', flat=True)),
                'winner_company_id': tender.winner_company_id,
                'status': tender.status,
                'is_completed_by_winner': tender.is_completed_by_winner,
                'created_at': tender.created_at.isoformat().replace('+00:00', 'Z'),
                'deadline': tender.deadline.isoformat().replace('+00:00', 'Z'),
            },
            format='json',
        )
        self.assertEqual(update.status_code, status.HTTP_200_OK)

        created = Tender.objects.create(
            title='Delete Me',
            organization='Temp',
            category='Temp',
            budget=Decimal('1000.00'),
            average_market_price=Decimal('900.00'),
            final_price=Decimal('950.00'),
            participants_count=1,
            status=Tender.Status.ACTIVE,
            created_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=2),
        )
        delete = self.client.delete(reverse('tender-detail', args=[created.external_id]))
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)
