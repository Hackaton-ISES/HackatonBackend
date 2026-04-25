from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.generics import GenericAPIView
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from tenders.models import Company, RiskReason, Tender, TenderBid, UserProfile, ensure_user_profile
from tenders.permissions import IsAdminOrReadOnly, IsAdminUserProfileOrStaff
from tenders.serializers import (
    AnalyzeTenderResponseSerializer,
    ApplicationSerializer,
    ApplicationStatusSerializer,
    AuthUserSerializer,
    CompanyRegistrationSerializer,
    CompanySerializer,
    FrontendApplicationCreateSerializer,
    FrontendApplicationSerializer,
    LoginSerializer,
    LoginResponseSerializer,
    RiskReasonSerializer,
    RiskStatsSerializer,
    TenderAnalysisSerializer,
    TenderCreateSerializer,
    TenderDetailSerializer,
    TenderWriteSerializer,
)
from tenders.services.risk_scoring import analyze_tender, get_risk_stats


def get_tender_by_identifier(identifier: str) -> Tender:
    query = Q(external_id=identifier)
    if identifier.isdigit():
        query |= Q(pk=int(identifier))
    return get_object_or_404(
        Tender.objects.select_related('winner_company', 'risk_analysis').prefetch_related(
            'participants', 'bids__company', 'risk_analysis__reasons'
        ),
        query,
    )


def get_bid_by_identifier(identifier: str) -> TenderBid:
    query = Q(external_id=identifier)
    if identifier.isdigit():
        query |= Q(pk=int(identifier))
    return get_object_or_404(TenderBid.objects.select_related('tender', 'company'), query)


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


class TenderListCreateAPIView(generics.ListCreateAPIView):
    queryset = (
        Tender.objects.select_related('winner_company', 'risk_analysis')
        .prefetch_related('participants', 'bids__company', 'risk_analysis__reasons')
        .order_by('-created_at', '-id')
    )
    permission_classes = [IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TenderCreateSerializer
        return TenderAnalysisSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['auto_analyze'] = False
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tender = serializer.save()
        output = TenderDetailSerializer(tender, context={'auto_analyze': False})
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)


class TenderDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdminOrReadOnly]
    lookup_url_kwarg = 'tender_id'

    def get_serializer_class(self):
        if self.request.method in {'PUT', 'PATCH'}:
            return TenderWriteSerializer
        return TenderDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['auto_analyze'] = True
        return context

    def get_object(self):
        return get_tender_by_identifier(self.kwargs['tender_id'])


class ApplicationListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = FrontendApplicationSerializer

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
            return Response({'detail': 'You can only submit bids for your own company.'}, status=status.HTTP_403_FORBIDDEN)

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
        tender.participants_count += 1
        tender.save(update_fields=['participants_count', 'updated_at'])
        company.update_statistics()
        analyze_tender(tender)

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

        if new_status == 'won':
            application.tender.bids.update(is_winner=False)
            application.is_winner = True
            application.save(update_fields=['is_winner'])
            application.tender.winner_company = application.company
            application.tender.status = Tender.Status.COMPLETED
            application.tender.save(update_fields=['winner_company', 'status', 'updated_at'])
        else:
            application.is_winner = False
            application.save(update_fields=['is_winner'])

        application.company.update_statistics()
        if application.tender.winner_company:
            application.tender.winner_company.update_statistics()
        analyze_tender(application.tender)
        return Response(FrontendApplicationSerializer(application).data)


class TenderAnalyzeAPIView(GenericAPIView):
    permission_classes = [IsAdminUserProfileOrStaff]
    serializer_class = AnalyzeTenderResponseSerializer

    @extend_schema(request=None, responses=AnalyzeTenderResponseSerializer)
    def post(self, request, pk: str):
        tender = get_tender_by_identifier(pk)
        analysis = analyze_tender(tender)
        serializer = AnalyzeTenderResponseSerializer(analysis)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RiskStatsAPIView(GenericAPIView):
    serializer_class = RiskStatsSerializer

    @extend_schema(responses=RiskStatsSerializer)
    def get(self, request):
        return Response(get_risk_stats())


class RiskFlagsAPIView(GenericAPIView):
    serializer_class = RiskReasonSerializer

    @extend_schema(responses=RiskReasonSerializer(many=True))
    def get(self, request, tender_id: str):
        tender = get_tender_by_identifier(tender_id)
        analysis = analyze_tender(tender)
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
