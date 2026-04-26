from django.urls import path

from tenders.views import (
    ApplicationListCreateAPIView,
    ApplicationStatusAPIView,
    CompanyAnalyzeAPIView,
    CompanyDetailAPIView,
    CompanyFlagsAPIView,
    CompanyListAPIView,
    CompanyStatsAPIView,
    LoginAPIView,
    LogoutAPIView,
    MeAPIView,
    TenderAwardRiskAPIView,
    TenderDetailAPIView,
    TenderFinalizeWinnerAPIView,
    TenderListCreateAPIView,
    UserListCreateAPIView,
)

urlpatterns = [
    path('auth/login', LoginAPIView.as_view(), name='auth-login'),
    path('auth/logout', LogoutAPIView.as_view(), name='auth-logout'),
    path('auth/me', MeAPIView.as_view(), name='auth-me'),
    path('users', UserListCreateAPIView.as_view(), name='users-list-create'),
    path('companies', CompanyListAPIView.as_view(), name='companies-list'),
    path('companies/<str:company_id>', CompanyDetailAPIView.as_view(), name='company-detail'),
    path('companies/<str:company_id>/analyze', CompanyAnalyzeAPIView.as_view(), name='company-analyze'),
    path('tenders', TenderListCreateAPIView.as_view(), name='tender-list-create'),
    path('tenders/<str:tender_id>', TenderDetailAPIView.as_view(), name='tender-detail'),
    path('tenders/<str:tender_id>/award-risk', TenderAwardRiskAPIView.as_view(), name='tender-award-risk'),
    path(
        'tenders/<str:tender_id>/finalize-winner',
        TenderFinalizeWinnerAPIView.as_view(),
        name='tender-finalize-winner',
    ),
    path('applications', ApplicationListCreateAPIView.as_view(), name='applications-list-create'),
    path('applications/<str:pk>/status', ApplicationStatusAPIView.as_view(), name='application-status'),
    path('risk/analyze/<str:company_id>', CompanyAnalyzeAPIView.as_view(), name='risk-analyze'),
    path('risk/stats', CompanyStatsAPIView.as_view(), name='risk-stats'),
    path('risk/flags/<str:company_id>', CompanyFlagsAPIView.as_view(), name='risk-flags'),
    path('api/companies/<str:company_id>/analyze/', CompanyAnalyzeAPIView.as_view(), name='company-analyze-api'),
]
