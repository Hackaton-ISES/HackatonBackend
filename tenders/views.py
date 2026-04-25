from rest_framework import generics

from tenders.models import Tender
from tenders.serializers import TenderAnalysisSerializer, TenderCreateSerializer


class TenderListCreateAPIView(generics.ListCreateAPIView):
    queryset = (
        Tender.objects.select_related('winner_company')
        .prefetch_related('participants')
        .order_by('-created_at', '-id')
    )

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TenderCreateSerializer
        return TenderAnalysisSerializer


class TenderDetailAPIView(generics.RetrieveAPIView):
    queryset = Tender.objects.select_related('winner_company').prefetch_related('participants')
    serializer_class = TenderAnalysisSerializer
