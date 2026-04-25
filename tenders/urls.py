from django.urls import path

from tenders.views import (
    ApplicationListCreateAPIView,
    ApplicationStatusAPIView,
    LoginAPIView,
    LogoutAPIView,
    MeAPIView,
    RiskFlagsAPIView,
    RiskStatsAPIView,
    TenderAnalyzeAPIView,
    TenderDetailAPIView,
    TenderListCreateAPIView,
    UserListCreateAPIView,
)

urlpatterns = [
    path('auth/login', LoginAPIView.as_view(), name='auth-login'),
    path('auth/logout', LogoutAPIView.as_view(), name='auth-logout'),
    path('auth/me', MeAPIView.as_view(), name='auth-me'),
    path('users', UserListCreateAPIView.as_view(), name='users-list-create'),
    path('tenders', TenderListCreateAPIView.as_view(), name='tender-list-create'),
    path('tenders/<str:tender_id>', TenderDetailAPIView.as_view(), name='tender-detail'),
    path('applications', ApplicationListCreateAPIView.as_view(), name='applications-list-create'),
    path('applications/<str:pk>/status', ApplicationStatusAPIView.as_view(), name='application-status'),
    path('risk/analyze/<str:pk>', TenderAnalyzeAPIView.as_view(), name='risk-analyze'),
    path('risk/stats', RiskStatsAPIView.as_view(), name='risk-stats'),
    path('risk/flags/<str:tender_id>', RiskFlagsAPIView.as_view(), name='risk-flags'),
    path('api/tenders/<str:pk>/analyze/', TenderAnalyzeAPIView.as_view(), name='tender-analyze'),
]
