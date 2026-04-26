from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from tenders.models import Company, CompanySuspicionAnalysis, Tender, TenderBid
from tenders.services.risk_scoring import (
    analyze_company,
    calculate_consecutive_wins_score,
    calculate_failed_delivery_score,
    calculate_fake_competition_score,
    calculate_price_score,
)


class CompanySuspicionServiceTests(APITestCase):
    def setUp(self):
        self.now = timezone.now()
        self.target = Company.objects.create(name='Target Co')
        self.other_one = Company.objects.create(name='Other One')
        self.other_two = Company.objects.create(name='Other Two')
        self.other_three = Company.objects.create(name='Other Three')

    def _create_tender(self, **overrides):
        values = {
            'title': 'Test Tender',
            'organization': 'Transport Agency',
            'category': 'Road Works',
            'budget': Decimal('100000.00'),
            'average_market_price': Decimal('80000.00'),
            'final_price': Decimal('98000.00'),
            'participants_count': 4,
            'winner_company': self.target,
            'status': Tender.Status.COMPLETED,
            'is_completed_by_winner': True,
            'created_at': self.now,
            'deadline': self.now + timezone.timedelta(days=5),
        }
        values.update(overrides)
        tender = Tender.objects.create(**values)
        tender.participants.set([self.target, self.other_one, self.other_two, self.other_three])
        return tender

    def test_price_score_calculation(self):
        self._create_tender(final_price=Decimal('120000.00'))
        result = calculate_price_score(self.target)
        self.assertGreater(result.score, 0)
        self.assertTrue(any(reason.title == 'Winner price anomaly' for reason in result.reasons))

    def test_failed_delivery_score_calculation(self):
        self._create_tender(is_completed_by_winner=False)
        result = calculate_failed_delivery_score(self.target)
        self.assertEqual(result.score, 20)

    def test_consecutive_wins_score_calculation(self):
        for index in range(2):
            self._create_tender(
                title=f'Past {index}',
                created_at=self.now - timezone.timedelta(days=4 - index),
                deadline=self.now - timezone.timedelta(days=2 - index),
            )
        self._create_tender(title='Current Consecutive')
        result = calculate_consecutive_wins_score(self.target)
        self.assertGreaterEqual(result.score, 10)

    def test_fake_competition_score_calculation(self):
        for index in range(4):
            previous = self._create_tender(
                title=f'Pattern {index}',
                created_at=self.now - timezone.timedelta(days=10 - index),
                deadline=self.now - timezone.timedelta(days=8 - index),
            )
            TenderBid.objects.create(
                tender=previous,
                company=self.target,
                bid_price=Decimal('100000.00') + Decimal(index),
                is_winner=True,
            )
            TenderBid.objects.create(
                tender=previous,
                company=self.other_one,
                bid_price=Decimal('101000.00') + Decimal(index),
                is_winner=False,
            )
            TenderBid.objects.create(
                tender=previous,
                company=self.other_two,
                bid_price=Decimal('101500.00') + Decimal(index),
                is_winner=False,
            )
            TenderBid.objects.create(
                tender=previous,
                company=self.other_three,
                bid_price=Decimal('101800.00') + Decimal(index),
                is_winner=False,
            )

        current = self._create_tender(title='Collusion Candidate')
        TenderBid.objects.create(tender=current, company=self.target, bid_price=Decimal('120000.00'), is_winner=True)
        TenderBid.objects.create(tender=current, company=self.other_one, bid_price=Decimal('121500.00'), is_winner=False)
        TenderBid.objects.create(tender=current, company=self.other_two, bid_price=Decimal('122000.00'), is_winner=False)
        TenderBid.objects.create(tender=current, company=self.other_three, bid_price=Decimal('122300.00'), is_winner=False)

        result = calculate_fake_competition_score(self.target)
        self.assertGreaterEqual(result.score, 25)

    def test_analyze_company_creates_suspicion_analysis_and_reasons(self):
        tender = self._create_tender(is_completed_by_winner=False, final_price=Decimal('120000.00'))
        TenderBid.objects.create(tender=tender, company=self.target, bid_price=Decimal('118000.00'), is_winner=True)
        TenderBid.objects.create(tender=tender, company=self.other_one, bid_price=Decimal('119000.00'), is_winner=False)
        TenderBid.objects.create(tender=tender, company=self.other_two, bid_price=Decimal('119500.00'), is_winner=False)

        analysis = analyze_company(self.target)
        self.assertIsInstance(analysis, CompanySuspicionAnalysis)
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
                is_completed_by_winner=False,
            )
            TenderBid.objects.create(tender=previous, company=self.target, bid_price=Decimal('90000.00'), is_winner=True)
            TenderBid.objects.create(tender=previous, company=self.other_one, bid_price=Decimal('91000.00'), is_winner=False)
            TenderBid.objects.create(tender=previous, company=self.other_two, bid_price=Decimal('91800.00'), is_winner=False)
            TenderBid.objects.create(tender=previous, company=self.other_three, bid_price=Decimal('91900.00'), is_winner=False)

        analysis = analyze_company(self.target)
        self.assertEqual(analysis.total_score, 100)

    @patch('tenders.services.risk_scoring.generate_company_summary', return_value='AI summary text')
    def test_analyze_company_persists_ai_summary(self, mocked_summary):
        self._create_tender(is_completed_by_winner=False, final_price=Decimal('120000.00'))
        analysis = analyze_company(self.target)
        self.assertEqual(analysis.ai_summary, 'AI summary text')
        mocked_summary.assert_called_once()


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

    def test_companies_register_company_with_account(self):
        response = self.client.post(
            reverse('companies-list'),
            {
                'username': 'company-via-companies-endpoint',
                'password': 'strongpass123',
                'company_name': 'Company Via Companies Endpoint',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='company-via-companies-endpoint')
        self.assertEqual(user.profile.company.name, 'Company Via Companies Endpoint')
        self.assertEqual(user.profile.external_id, user.profile.company.external_id)

    def test_plain_user_creation_gets_profile_automatically(self):
        user = User.objects.create_user(username='autoprofile', password='strongpass123')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertEqual(user.profile.role, 'company')

    def test_tender_list_requires_auth(self):
        response = self.client.get(reverse('tender-list-create'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_tenders_returns_plain_tender_payload(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        response = self.client.get(reverse('tender-list-create'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('results', response.data)
        self.assertIn('title', response.data['results'][0])
        self.assertNotIn('riskScore', response.data['results'][0])

    def test_companies_endpoint_returns_suspicion_payload(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        response = self.client.get(reverse('companies-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('results', response.data)
        self.assertIn('suspicionScore', response.data['results'][0])
        self.assertIn('suspicionLevel', response.data['results'][0])
        self.assertIn('suspicionFlags', response.data['results'][0])

    def test_tenders_endpoint_supports_page_and_page_size(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        response = self.client.get(reverse('tender-list-create'), {'page': 1, 'page_size': 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], Tender.objects.count())
        self.assertEqual(len(response.data['results']), 2)

    def test_applications_endpoint_paginates_filtered_queryset(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        company = Company.objects.get(external_id='c-acme')
        for index in range(3):
            tender = Tender.objects.create(
                title=f'Pagination Tender {index}',
                organization='Pagination Agency',
                category='Supplies',
                budget=Decimal('100000.00'),
                average_market_price=Decimal('95000.00'),
                final_price=Decimal('0.00'),
                participants_count=0,
                status=Tender.Status.ACTIVE,
                created_at=timezone.now(),
                deadline=timezone.now() + timezone.timedelta(days=5),
            )
            TenderBid.objects.create(
                tender=tender,
                company=company,
                bid_price=Decimal('90000.00') + Decimal(index),
                product_name=f'Product {index}',
                product_description=f'Description {index}',
            )
        response = self.client.get(
            reverse('applications-list-create'),
            {'companyId': company.external_id, 'page': 1, 'page_size': 2},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('results', response.data)
        self.assertEqual(response.data['count'], TenderBid.objects.filter(company=company).count())
        self.assertEqual(len(response.data['results']), 2)
        self.assertTrue(all(item['companyId'] == company.external_id for item in response.data['results']))

    def test_company_user_applications_endpoint_paginates_own_records_only(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.company_token.key}')
        company = Company.objects.get(external_id='c-acme')
        other_company = Company.objects.get(external_id='c-nova')
        for index in range(3):
            tender = Tender.objects.create(
                title=f'Company Pagination Tender {index}',
                organization='Company Pagination Agency',
                category='Services',
                budget=Decimal('100000.00'),
                average_market_price=Decimal('95000.00'),
                final_price=Decimal('0.00'),
                participants_count=0,
                status=Tender.Status.ACTIVE,
                created_at=timezone.now(),
                deadline=timezone.now() + timezone.timedelta(days=5),
            )
            TenderBid.objects.create(
                tender=tender,
                company=company,
                bid_price=Decimal('91000.00') + Decimal(index),
                product_name=f'Own Product {index}',
                product_description=f'Own Description {index}',
            )
        other_tender = Tender.objects.create(
            title='Company Pagination Other Tender',
            organization='Company Pagination Agency',
            category='Services',
            budget=Decimal('100000.00'),
            average_market_price=Decimal('95000.00'),
            final_price=Decimal('0.00'),
            participants_count=0,
            status=Tender.Status.ACTIVE,
            created_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=5),
        )
        TenderBid.objects.create(
            tender=other_tender,
            company=other_company,
            bid_price=Decimal('98000.00'),
            product_name='Other Product',
            product_description='Other Description',
        )
        response = self.client.get(reverse('applications-list-create'), {'page': 1, 'page_size': 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], TenderBid.objects.filter(company=company).count())
        self.assertEqual(len(response.data['results']), 2)
        self.assertTrue(all(item['companyId'] == company.external_id for item in response.data['results']))

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
        tender = Tender.objects.create(
            title='Patch Status Tender',
            organization='Patch Org',
            category='Patch Category',
            budget=Decimal('100000.00'),
            average_market_price=Decimal('95000.00'),
            final_price=Decimal('0.00'),
            participants_count=0,
            status=Tender.Status.ACTIVE,
            created_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=3),
        )
        company_one = Company.objects.get(external_id='c-acme')
        company_two = Company.objects.get(external_id='c-nova')
        tender.participants.set([company_one, company_two])
        bid = TenderBid.objects.create(
            tender=tender,
            company=company_one,
            bid_price=Decimal('97000.00'),
            product_name='Patch Product',
            product_description='Patch Description',
        )
        TenderBid.objects.create(
            tender=tender,
            company=company_two,
            bid_price=Decimal('98000.00'),
            product_name='Patch Product 2',
            product_description='Patch Description 2',
        )
        response = self.client.patch(
            reverse('application-status', args=[bid.external_id]),
            {'status': 'won'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bid.refresh_from_db()
        self.assertTrue(bid.is_winner)
        self.assertEqual(response.data['status'], 'Won')

    def test_admin_can_finalize_winner_atomically(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        tender = Tender.objects.create(
            title='Finalize Winner Tender',
            organization='Water Agency',
            category='Pumps',
            budget=Decimal('100000.00'),
            average_market_price=Decimal('95000.00'),
            final_price=Decimal('0.00'),
            participants_count=0,
            status=Tender.Status.ACTIVE,
            created_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=3),
        )
        tender.participants.set([Company.objects.get(external_id='c-acme'), Company.objects.get(external_id='c-nova')])
        bid_one = TenderBid.objects.create(
            tender=tender,
            company=Company.objects.get(external_id='c-acme'),
            bid_price=Decimal('97000.00'),
            product_name='Pump A',
            product_description='Pump A description',
        )
        bid_two = TenderBid.objects.create(
            tender=tender,
            company=Company.objects.get(external_id='c-nova'),
            bid_price=Decimal('98000.00'),
            product_name='Pump B',
            product_description='Pump B description',
        )

        response = self.client.post(
            reverse('tender-finalize-winner', args=[tender.external_id]),
            {'applicationId': bid_one.external_id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tender.refresh_from_db()
        bid_one.refresh_from_db()
        bid_two.refresh_from_db()
        self.assertEqual(tender.winner_company.external_id, 'c-acme')
        self.assertEqual(tender.final_price, Decimal('97000.00'))
        self.assertEqual(tender.status, Tender.Status.COMPLETED)
        self.assertTrue(bid_one.is_winner)
        self.assertFalse(bid_two.is_winner)
        self.assertTrue(response.data['locked'])
        self.assertEqual(response.data['winnerApplicationId'], bid_one.external_id)
        self.assertEqual({item['status'] for item in response.data['applications']}, {'Won', 'Lost'})

    def test_tender_award_risk_returns_participant_recommendations(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        company = Company.objects.get(external_id='c-acme')
        company.total_wins = 7
        company.failed_projects = 3
        company.total_participations = 10
        company.completed_projects = 4
        company.save(
            update_fields=[
                'total_wins',
                'failed_projects',
                'total_participations',
                'completed_projects',
                'updated_at',
            ]
        )
        tender = Tender.objects.create(
            title='Award Risk Tender',
            organization='Audit Agency',
            category='Construction',
            budget=Decimal('100000.00'),
            average_market_price=Decimal('100000.00'),
            final_price=Decimal('0.00'),
            participants_count=0,
            status=Tender.Status.ACTIVE,
            created_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=3),
        )
        bid = TenderBid.objects.create(
            tender=tender,
            company=company,
            bid_price=Decimal('140000.00'),
            product_name='Risk Product',
            product_description='Risk Description',
        )
        response = self.client.get(reverse('tender-award-risk', args=[tender.external_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['tenderId'], tender.external_id)
        self.assertEqual(response.data['baseline']['source'], 'average_market_price')
        participant = response.data['participants'][0]
        self.assertEqual(participant['applicationId'], bid.external_id)
        self.assertEqual(participant['companyId'], company.external_id)
        self.assertEqual(participant['recommendation'], 'audit_required')
        self.assertEqual(participant['recommendationLabel'], 'Do not award without audit')
        self.assertGreaterEqual(len(participant['reasons']), 1)

    def test_finalize_winner_requires_audit_for_audit_required_company(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        company = Company.objects.get(external_id='c-acme')
        company.total_wins = 7
        company.failed_projects = 3
        company.total_participations = 10
        company.completed_projects = 4
        company.save(
            update_fields=[
                'total_wins',
                'failed_projects',
                'total_participations',
                'completed_projects',
                'updated_at',
            ]
        )
        tender = Tender.objects.create(
            title='Audit Guard Tender',
            organization='Audit Guard Agency',
            category='Construction',
            budget=Decimal('100000.00'),
            average_market_price=Decimal('100000.00'),
            final_price=Decimal('0.00'),
            participants_count=0,
            status=Tender.Status.ACTIVE,
            created_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=3),
        )
        bid = TenderBid.objects.create(
            tender=tender,
            company=company,
            bid_price=Decimal('140000.00'),
            product_name='Guard Product',
            product_description='Guard Description',
        )
        response = self.client.post(
            reverse('tender-finalize-winner', args=[tender.external_id]),
            {'applicationId': bid.external_id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], 'Audit approval is required before awarding this company.')
        tender.refresh_from_db()
        bid.refresh_from_db()
        self.assertIsNone(tender.winner_company)
        self.assertFalse(bid.is_winner)

    def test_tender_update_is_locked_after_winner_finalization(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        tender = Tender.objects.get(title='Road Rehabilitation Package 5')
        response = self.client.put(
            reverse('tender-detail', args=[tender.external_id]),
            {
                'title': 'Attempted Update',
                'organization': tender.organization,
                'category': tender.category,
                'budget': str(tender.budget),
                'average_market_price': str(tender.average_market_price),
                'deadline': tender.deadline.isoformat().replace('+00:00', 'Z'),
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_application_status_cannot_change_after_finalization(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        tender = Tender.objects.get(title='Road Rehabilitation Package 5')
        winner_bid = tender.bids.get(is_winner=True)
        response = self.client.patch(
            reverse('application-status', args=[winner_bid.external_id]),
            {'status': 'won'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_tender_detail_exposes_winner_locked(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        tender = Tender.objects.get(title='Road Rehabilitation Package 5')
        response = self.client.get(reverse('tender-detail', args=[tender.external_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['winnerLocked'])

    def test_company_risk_endpoint_returns_analysis(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        company = Company.objects.get(name='Alpha Infrastructure')
        response = self.client.post(reverse('risk-analyze', args=[company.external_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('totalScore', response.data)
        self.assertIn('suspicionFlags', response.data)

    def test_company_flags_endpoint_returns_reasons(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        company = Company.objects.get(name='Alpha Infrastructure')
        response = self.client.get(reverse('risk-flags', args=[company.external_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertIn('severity', response.data[0])
        self.assertIn('message', response.data[0])

    def test_company_stats_endpoint_returns_distribution(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        response = self.client.get(reverse('risk-stats'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('total', response.data)
        self.assertIn('high', response.data)
        self.assertIn('medium', response.data)
        self.assertIn('low', response.data)
        self.assertIn('distribution', response.data)
        self.assertIn('top_suspicious_companies', response.data)

    def test_admin_can_update_and_delete_tender(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.admin_token.key}')
        tender = Tender.objects.create(
            title='Editable Tender',
            organization='Temp Org',
            category='Temp Category',
            budget=Decimal('1000.00'),
            average_market_price=Decimal('900.00'),
            final_price=Decimal('0.00'),
            participants_count=0,
            status=Tender.Status.ACTIVE,
            created_at=timezone.now(),
            deadline=timezone.now() + timezone.timedelta(days=2),
        )
        update = self.client.put(
            reverse('tender-detail', args=[tender.external_id]),
            {
                'title': 'Editable Tender Updated',
                'organization': tender.organization,
                'category': tender.category,
                'budget': '1100.00',
                'average_market_price': str(tender.average_market_price),
                'deadline': tender.deadline.isoformat().replace('+00:00', 'Z'),
            },
            format='json',
        )
        self.assertEqual(update.status_code, status.HTTP_200_OK)
        tender.refresh_from_db()
        self.assertEqual(tender.title, 'Editable Tender Updated')
        self.assertEqual(tender.budget, Decimal('1100.00'))

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
