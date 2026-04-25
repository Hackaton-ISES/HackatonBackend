from django.urls import path

from tenders.views import TenderDetailAPIView, TenderListCreateAPIView

urlpatterns = [
    path('tenders', TenderListCreateAPIView.as_view(), name='tender-list-create'),
    path('tenders/<int:pk>', TenderDetailAPIView.as_view(), name='tender-detail'),
]
