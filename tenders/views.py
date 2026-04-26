from django.contrib.auth import logout
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from tenders.models import Company, Tender, TenderBid, UserProfile, ensure_user_profile
from tenders.pagination import StandardResultsSetPagination
from tenders.permissions import IsAdminOrReadOnly, IsAdminUserProfileOrStaff
from tenders.serializers import (
    AnalyzeCompanyResponseSerializer,
    ApplicationSerializer,
    ApplicationStatusSerializer,
    AwardRiskResponseSerializer,
    AuthUserSerializer,
    CompanyDetailSerializer,
    CompanyRegistrationSerializer,
    CompanySerializer,
    CompanyStatsSerializer,
    FinalizeWinnerResponseSerializer,
    FinalizeWinnerSerializer,
    FrontendApplicationCreateSerializer,
    FrontendApplicationSerializer,
    LoginResponseSerializer,
    LoginSerializer,
    SuspicionFlagSerializer,
    TenderAnalysisSerializer,
    TenderCreateSerializer,
    TenderDetailSerializer,
    TenderWriteSerializer,
)
from tenders.services.award_risk import get_tender_award_risk
from tenders.services.risk_scoring import analyze_all_companies, analyze_company, get_company_stats
from tenders.services.tender_finalization import finalize_tender_winner


def get_tender_by_identifier(identifier: str) -> Tender:
    query = Q(external_id=identifier)
    if identifier.isdigit():
        query |= Q(pk=int(identifier))
    return get_object_or_404(
        Tender.objects.select_related('winner_company').prefetch_related('participants', 'bids__company'),
        query,
    )


def get_bid_by_identifier(identifier: str) -> TenderBid:
    query = Q(external_id=identifier)
    if identifier.isdigit():
        query |= Q(pk=int(identifier))
    return get_object_or_404(TenderBid.objects.select_related('tender', 'company'), query)


def get_company_by_identifier(identifier: str) -> Company:
    query = Q(external_id=identifier)
    if identifier.isdigit():
        query |= Q(pk=int(identifier))
    return get_object_or_404(
        Company.objects.prefetch_related('won_tenders__participants', 'won_tenders__bids__company'),
        query,
    )


class LoginAPIView(GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    @extend_schema(responses=LoginResponseSerializer)
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        ensure_user_profile(user)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({'user': AuthUserSerializer(user).data, 'token': token.key})


class LogoutAPIView(GenericAPIView):
    serializer_class = None

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeAPIView(GenericAPIView):
    serializer_class = AuthUserSerializer

    @extend_schema(responses=AuthUserSerializer)
    def get(self, request):
        ensure_user_profile(request.user)
        return Response(AuthUserSerializer(request.user).data)


class CompanyListAPIView(generics.ListCreateAPIView):
    queryset = Company.objects.order_by('name')
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CompanyRegistrationSerializer
        return CompanySerializer

    @extend_schema(request=CompanyRegistrationSerializer, responses=LoginResponseSerializer)
    def post(self, request, *args, **kwargs):
        serializer = CompanyRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {'user': AuthUserSerializer(user).data, 'token': token.key},
            status=status.HTTP_201_CREATED,
        )


class CompanyDetailAPIView(generics.RetrieveAPIView):
    serializer_class = CompanyDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_url_kwarg = 'company_id'

    def get_object(self):
        return get_company_by_identifier(self.kwargs['company_id'])


class TenderListCreateAPIView(generics.ListCreateAPIView):
    queryset = (
        Tender.objects.select_related('winner_company')
        .prefetch_related('participants', 'bids__company')
        .order_by('-created_at', '-id')
    )
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TenderCreateSerializer
        return TenderAnalysisSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tender = serializer.save()
        analyze_all_companies()
        output = TenderDetailSerializer(tender)
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)


class TenderDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdminOrReadOnly]
    lookup_url_kwarg = 'tender_id'

    def get_serializer_class(self):
        if self.request.method in {'PUT', 'PATCH'}:
            return TenderWriteSerializer
        return TenderDetailSerializer

    def get_object(self):
        return get_tender_by_identifier(self.kwargs['tender_id'])

    def update(self, request, *args, **kwargs):
        tender = self.get_object()
        if tender.winner_company_id:
            return Response(
                {'detail': 'Tender fields are locked after winner finalization.'},
                status=status.HTTP_409_CONFLICT,
            )
        return super().update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        instance.delete()
        analyze_all_companies()


class ApplicationListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = FrontendApplicationSerializer
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return FrontendApplicationCreateSerializer
        return FrontendApplicationSerializer

    def get_queryset(self):
        queryset = TenderBid.objects.select_related('company', 'tender').order_by('-created_at')
        company_id = self.request.query_params.get('companyId')
        tender_id = self.request.query_params.get('tenderId')
        profile = getattr(self.request.user, 'profile', None)

        if company_id:
            queryset = queryset.filter(company__external_id=company_id)
        if tender_id:
            queryset = queryset.filter(tender__external_id=tender_id)

        if not self.request.user.is_staff and profile and profile.role == UserProfile.Role.COMPANY:
            queryset = queryset.filter(company=profile.company)
        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = FrontendApplicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        tender = get_object_or_404(Tender, external_id=payload['tenderId'])
        company = get_object_or_404(Company, external_id=payload['companyId'])

        profile = getattr(request.user, 'profile', None)
        if not request.user.is_staff and (not profile or profile.company_id != company.id):
            return Response(
                {'detail': 'You can only submit bids for your own company.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        application = TenderBid.objects.create(
            tender=tender,
            company=company,
            bid_price=payload['proposedPrice'],
            product_name=payload['productName'],
            product_description=payload['productDescription'],
        )
        if payload['companyName'] and company.name != payload['companyName']:
            company.name = payload['companyName']
            company.save(update_fields=['name', 'updated_at'])

        tender.participants.add(company)
        tender.participants_count = tender.get_actual_participants_count()
        tender.save(update_fields=['participants_count', 'updated_at'])
        analyze_all_companies()

        output = FrontendApplicationSerializer(application)
        return Response(output.data, status=status.HTTP_201_CREATED)


class ApplicationStatusAPIView(GenericAPIView):
    permission_classes = [IsAdminUserProfileOrStaff]
    serializer_class = ApplicationStatusSerializer

    @transaction.atomic
    @extend_schema(request=ApplicationStatusSerializer, responses=ApplicationSerializer)
    def patch(self, request, pk: str):
        application = get_bid_by_identifier(pk)
        serializer = ApplicationStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        if application.tender.winner_company_id:
            return Response(
                {'detail': 'Winner has already been finalized for this tender.'},
                status=status.HTTP_409_CONFLICT,
            )

        if new_status != 'won':
            return Response(
                {'detail': 'Use tender winner finalization to select the winner.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            finalize_tender_winner(tender=application.tender, application=application)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)

        application.refresh_from_db()
        return Response(FrontendApplicationSerializer(application).data)


class TenderFinalizeWinnerAPIView(GenericAPIView):
    permission_classes = [IsAdminUserProfileOrStaff]
    serializer_class = FinalizeWinnerSerializer

    @extend_schema(request=FinalizeWinnerSerializer, responses=FinalizeWinnerResponseSerializer)
    def post(self, request, tender_id: str):
        tender = get_tender_by_identifier(tender_id)
        serializer = FinalizeWinnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application = get_bid_by_identifier(serializer.validated_data['applicationId'])

        try:
            finalize_tender_winner(tender=tender, application=application)
        except ValueError as exc:
            status_code = (
                status.HTTP_400_BAD_REQUEST
                if 'does not belong' in str(exc)
                else status.HTTP_409_CONFLICT
            )
            return Response({'detail': str(exc)}, status=status_code)

        tender = get_tender_by_identifier(tender_id)
        winner_bid = tender.bids.filter(is_winner=True).first()
        payload = {
            'tenderId': tender.external_id,
            'winnerCompanyId': tender.winner_company.external_id if tender.winner_company else None,
            'winnerApplicationId': winner_bid.external_id if winner_bid else application.external_id,
            'locked': bool(tender.winner_company_id),
            'applications': FrontendApplicationSerializer(tender.bids.all(), many=True).data,
        }
        return Response(payload, status=status.HTTP_200_OK)


class TenderAwardRiskAPIView(GenericAPIView):
    permission_classes = [IsAdminUserProfileOrStaff]
    serializer_class = AwardRiskResponseSerializer

    @extend_schema(responses=AwardRiskResponseSerializer)
    def get(self, request, tender_id: str):
        tender = get_tender_by_identifier(tender_id)
        return Response(get_tender_award_risk(tender))


class CompanyAnalyzeAPIView(GenericAPIView):
    permission_classes = [IsAdminUserProfileOrStaff]
    serializer_class = AnalyzeCompanyResponseSerializer

    @extend_schema(request=None, responses=AnalyzeCompanyResponseSerializer)
    def post(self, request, company_id: str):
        company = get_company_by_identifier(company_id)
        analysis = analyze_company(company)
        serializer = AnalyzeCompanyResponseSerializer(analysis)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CompanyStatsAPIView(GenericAPIView):
    serializer_class = CompanyStatsSerializer

    @extend_schema(responses=CompanyStatsSerializer)
    def get(self, request):
        return Response(get_company_stats())


class CompanyFlagsAPIView(GenericAPIView):
    serializer_class = SuspicionFlagSerializer

    @extend_schema(responses=SuspicionFlagSerializer(many=True))
    def get(self, request, company_id: str):
        company = get_company_by_identifier(company_id)
        analysis = analyze_company(company)
        return Response(
            [
                {
                    'severity': 'critical' if reason.score >= 15 else 'warning',
                    'message': reason.description,
                }
                for reason in analysis.reasons.all()
            ]
        )


class UserListCreateAPIView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = CompanyRegistrationSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.AllowAny()]
        return [IsAdminUserProfileOrStaff()]

    @extend_schema(responses=CompanySerializer(many=True))
    def get(self, request):
        companies = Company.objects.order_by('name')
        return Response(CompanySerializer(companies, many=True).data)

    @extend_schema(request=CompanyRegistrationSerializer, responses=LoginResponseSerializer)
    def post(self, request):
        serializer = CompanyRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {'user': AuthUserSerializer(user).data, 'token': token.key},
            status=status.HTTP_201_CREATED,
        )
