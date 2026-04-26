from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from tenders.models import (
    Company,
    CompanySuspicionAnalysis,
    CompanySuspicionReason,
    Tender,
    TenderBid,
    UserProfile,
    ensure_user_profile,
)
from tenders.services.account_creation import create_company_account
from tenders.services.risk_scoring import analyze_all_companies, analyze_company


class SuspicionReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanySuspicionReason
        fields = ['id', 'title', 'description', 'score', 'created_at']


class SuspicionFlagSerializer(serializers.Serializer):
    severity = serializers.ChoiceField(choices=['warning', 'critical'])
    message = serializers.CharField()


class CompanySuspicionAnalysisSerializer(serializers.ModelSerializer):
    reasons = SuspicionReasonSerializer(many=True, read_only=True)

    class Meta:
        model = CompanySuspicionAnalysis
        fields = [
            'total_score',
            'suspicion_level',
            'price_score',
            'failed_delivery_score',
            'consecutive_wins_score',
            'fake_competition_score',
            'ai_summary',
            'analyzed_at',
            'reasons',
        ]


class CompanySerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='external_id', read_only=True)
    suspicionScore = serializers.SerializerMethodField()
    suspicionLevel = serializers.SerializerMethodField()
    suspicionFlags = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            'id',
            'name',
            'total_participations',
            'total_wins',
            'completed_projects',
            'failed_projects',
            'created_at',
            'updated_at',
            'suspicionScore',
            'suspicionLevel',
            'suspicionFlags',
        ]

    def _get_analysis(self, obj: Company) -> CompanySuspicionAnalysis:
        if not hasattr(obj, '_analysis_cache'):
            try:
                obj._analysis_cache = obj.suspicion_analysis
            except CompanySuspicionAnalysis.DoesNotExist:
                obj._analysis_cache = analyze_company(obj)
        return obj._analysis_cache

    @extend_schema_field(serializers.IntegerField)
    def get_suspicionScore(self, obj):
        return self._get_analysis(obj).total_score

    @extend_schema_field(serializers.CharField)
    def get_suspicionLevel(self, obj):
        return self._get_analysis(obj).suspicion_level.upper()

    @extend_schema_field(SuspicionFlagSerializer(many=True))
    def get_suspicionFlags(self, obj):
        return [
            {
                'severity': 'critical' if reason.score >= 15 else 'warning',
                'message': reason.description,
            }
            for reason in self._get_analysis(obj).reasons.all()
        ]


class CompanyDetailSerializer(CompanySerializer):
    suspicionAnalysis = serializers.SerializerMethodField()
    reasons = serializers.SerializerMethodField()

    class Meta(CompanySerializer.Meta):
        fields = CompanySerializer.Meta.fields + ['suspicionAnalysis', 'reasons']

    @extend_schema_field(CompanySuspicionAnalysisSerializer)
    def get_suspicionAnalysis(self, obj):
        return CompanySuspicionAnalysisSerializer(self._get_analysis(obj)).data

    @extend_schema_field(SuspicionReasonSerializer(many=True))
    def get_reasons(self, obj):
        return SuspicionReasonSerializer(self._get_analysis(obj).reasons.all(), many=True).data


class UserProfileSerializer(serializers.ModelSerializer):
    company = CompanySerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = ['role', 'company']


class AuthUserSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    login = serializers.CharField(source='username', read_only=True)
    name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'login', 'name', 'role']

    def get_id(self, obj):
        return ensure_user_profile(obj).external_id

    def get_name(self, obj):
        profile = ensure_user_profile(obj)
        if profile.role == UserProfile.Role.ADMIN:
            full_name = f'{obj.first_name} {obj.last_name}'.strip()
            return full_name or 'System Admin'
        if profile.company:
            return profile.company.name
        return obj.username

    def get_role(self, obj):
        return ensure_user_profile(obj).role


class LoginResponseSerializer(serializers.Serializer):
    user = AuthUserSerializer()
    token = serializers.CharField()


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        login_value = attrs['login'].strip()
        user = User.objects.filter(username__iexact=login_value).first()
        if user is not None:
            user = authenticate(username=user.username, password=attrs['password'])
        if user is None:
            raise serializers.ValidationError('Invalid login or password')
        attrs['user'] = user
        return attrs


class CompanyRegistrationSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=8)
    email = serializers.EmailField(required=False, allow_blank=True)
    company_name = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    @transaction.atomic
    def create(self, validated_data):
        return create_company_account(
            company_name=validated_data['company_name'],
            username=validated_data['username'],
            password=validated_data['password'],
            email=validated_data.get('email', ''),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )


class CompanyStatsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    high = serializers.IntegerField()
    medium = serializers.IntegerField()
    low = serializers.IntegerField()
    distribution = serializers.DictField(child=serializers.IntegerField())
    top_suspicious_companies = serializers.ListField(child=serializers.DictField())
    total_analyzed_companies = serializers.IntegerField()


class TenderAnalysisSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='external_id', read_only=True)
    participantsCount = serializers.SerializerMethodField()
    averageMarketPrice = serializers.DecimalField(
        source='average_market_price',
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    finalPrice = serializers.DecimalField(
        source='final_price',
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    winnerCompanyId = serializers.SerializerMethodField()
    winnerLocked = serializers.SerializerMethodField()

    class Meta:
        model = Tender
        fields = [
            'id',
            'title',
            'organization',
            'category',
            'budget',
            'averageMarketPrice',
            'finalPrice',
            'participantsCount',
            'winnerCompanyId',
            'winnerLocked',
            'status',
            'createdAt',
            'deadline',
        ]

    @extend_schema_field(serializers.IntegerField)
    def get_participantsCount(self, obj):
        return obj.get_actual_participants_count()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_winnerCompanyId(self, obj):
        return obj.winner_company.external_id if obj.winner_company else None

    @extend_schema_field(serializers.BooleanField)
    def get_winnerLocked(self, obj):
        return bool(obj.winner_company_id)


class TenderDetailSerializer(TenderAnalysisSerializer):
    bids = serializers.SerializerMethodField()

    class Meta(TenderAnalysisSerializer.Meta):
        fields = TenderAnalysisSerializer.Meta.fields + ['bids']

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_bids(self, obj):
        return FrontendApplicationSerializer(obj.bids.all(), many=True).data


class TenderCreateSerializer(serializers.ModelSerializer):
    final_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        default=Decimal('0.00'),
    )

    class Meta:
        model = Tender
        fields = [
            'id',
            'title',
            'organization',
            'category',
            'budget',
            'average_market_price',
            'final_price',
            'created_at',
            'deadline',
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        created_at = attrs.get('created_at')
        deadline = attrs.get('deadline')
        if created_at and deadline and deadline <= created_at:
            raise serializers.ValidationError({'deadline': 'Deadline must be later than created_at.'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        return Tender.objects.create(
            participants_count=0,
            status=Tender.Status.ACTIVE,
            is_completed_by_winner=None,
            winner_company=None,
            **validated_data,
        )


class TenderWriteSerializer(serializers.ModelSerializer):
    winnerCompanyId = serializers.SerializerMethodField(read_only=True)
    winnerLocked = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Tender
        fields = [
            'id',
            'title',
            'organization',
            'category',
            'budget',
            'average_market_price',
            'final_price',
            'created_at',
            'deadline',
            'status',
            'winnerCompanyId',
            'winnerLocked',
        ]
        read_only_fields = [
            'id',
            'final_price',
            'created_at',
            'status',
            'winnerCompanyId',
            'winnerLocked',
        ]

    def validate(self, attrs):
        created_at = getattr(self.instance, 'created_at', None)
        deadline = attrs.get('deadline', getattr(self.instance, 'deadline', None))
        if created_at and deadline and deadline <= created_at:
            raise serializers.ValidationError({'deadline': 'Deadline must be later than created_at.'})
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        analyze_all_companies()
        return instance

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_winnerCompanyId(self, obj):
        return obj.winner_company.external_id if obj.winner_company else None

    @extend_schema_field(serializers.BooleanField)
    def get_winnerLocked(self, obj):
        return bool(obj.winner_company_id)


class ApplicationSerializer(serializers.ModelSerializer):
    company = CompanySerializer(read_only=True)
    tender = TenderAnalysisSerializer(read_only=True)
    company_id = serializers.IntegerField(write_only=True, required=False)
    tender_id = serializers.PrimaryKeyRelatedField(
        queryset=Tender.objects.all(),
        source='tender',
        write_only=True,
    )
    status = serializers.CharField(read_only=True)

    class Meta:
        model = TenderBid
        fields = [
            'id',
            'tender',
            'company',
            'bid_price',
            'is_winner',
            'status',
            'created_at',
            'company_id',
            'tender_id',
        ]
        read_only_fields = ['id', 'is_winner', 'status', 'created_at', 'tender', 'company']

    def validate(self, attrs):
        tender = attrs['tender']
        company_id = attrs.pop('company_id', None)
        company = Company.objects.filter(pk=company_id).first() if company_id else None
        request = self.context['request']
        profile = getattr(request.user, 'profile', None)

        if request.user.is_staff:
            pass
        elif profile and profile.company:
            company = profile.company
            attrs['company'] = company
        else:
            raise serializers.ValidationError('A company profile is required to submit bids.')

        if tender.status != Tender.Status.ACTIVE:
            raise serializers.ValidationError('Bids can only be submitted to active tenders.')
        if company is None:
            raise serializers.ValidationError({'company_id': 'Company is required.'})

        attrs['company'] = company
        if tender.deadline <= tender.created_at:
            raise serializers.ValidationError('Tender deadline is invalid.')
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        application = TenderBid.objects.create(**validated_data)
        application.tender.participants.add(application.company)
        application.tender.participants_count = application.tender.get_actual_participants_count()
        application.tender.save(update_fields=['participants_count', 'updated_at'])
        analyze_all_companies()
        return application


class ApplicationStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['won', 'lost'])


class FrontendApplicationSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='external_id', read_only=True)
    tenderId = serializers.CharField(source='tender.external_id', read_only=True)
    companyId = serializers.CharField(source='company.external_id', read_only=True)
    companyName = serializers.CharField(source='company.name', read_only=True)
    proposedPrice = serializers.DecimalField(
        source='bid_price',
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    productName = serializers.CharField(source='product_name', read_only=True)
    productDescription = serializers.CharField(source='product_description', read_only=True)
    status = serializers.SerializerMethodField()
    submittedAt = serializers.SerializerMethodField()

    class Meta:
        model = TenderBid
        fields = [
            'id',
            'tenderId',
            'companyId',
            'companyName',
            'proposedPrice',
            'productName',
            'productDescription',
            'status',
            'submittedAt',
        ]

    def get_status(self, obj):
        if obj.is_winner:
            return 'Won'
        if obj.tender.winner_company_id:
            return 'Lost'
        return 'Pending'

    def get_submittedAt(self, obj):
        return obj.created_at.date().isoformat()


class FrontendApplicationCreateSerializer(serializers.Serializer):
    tenderId = serializers.CharField()
    companyId = serializers.CharField()
    companyName = serializers.CharField(min_length=1, max_length=100)
    proposedPrice = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.01'),
    )
    productName = serializers.CharField(min_length=1, max_length=120)
    productDescription = serializers.CharField(min_length=1, max_length=1000)


class AnalyzeCompanyResponseSerializer(serializers.ModelSerializer):
    companyId = serializers.CharField(source='company.external_id', read_only=True)
    companyName = serializers.CharField(source='company.name', read_only=True)
    totalScore = serializers.IntegerField(source='total_score', read_only=True)
    suspicionLevel = serializers.SerializerMethodField()
    suspicionFlags = serializers.SerializerMethodField()

    class Meta:
        model = CompanySuspicionAnalysis
        fields = [
            'companyId',
            'companyName',
            'totalScore',
            'suspicionLevel',
            'price_score',
            'failed_delivery_score',
            'consecutive_wins_score',
            'fake_competition_score',
            'ai_summary',
            'suspicionFlags',
        ]

    @extend_schema_field(serializers.CharField)
    def get_suspicionLevel(self, obj):
        return obj.suspicion_level.upper()

    @extend_schema_field(SuspicionFlagSerializer(many=True))
    def get_suspicionFlags(self, obj):
        return [
            {
                'severity': 'critical' if reason.score >= 15 else 'warning',
                'message': reason.description,
            }
            for reason in obj.reasons.all()
        ]


class FinalizeWinnerSerializer(serializers.Serializer):
    applicationId = serializers.CharField()


class FinalizeWinnerResponseSerializer(serializers.Serializer):
    tenderId = serializers.CharField()
    winnerCompanyId = serializers.CharField(allow_null=True)
    winnerApplicationId = serializers.CharField()
    locked = serializers.BooleanField()
    applications = FrontendApplicationSerializer(many=True)


class AwardRiskReasonSerializer(serializers.Serializer):
    rule = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    severity = serializers.CharField()
    points = serializers.IntegerField()


class AwardRiskParticipantSerializer(serializers.Serializer):
    applicationId = serializers.CharField()
    companyId = serializers.CharField()
    companyName = serializers.CharField()
    proposedPrice = serializers.DecimalField(max_digits=14, decimal_places=2)
    priceDeltaPercent = serializers.IntegerField()
    companySuspicionScore = serializers.IntegerField()
    companySuspicionLevel = serializers.CharField()
    failedProjects = serializers.IntegerField()
    totalWins = serializers.IntegerField()
    recommendation = serializers.CharField()
    recommendationLabel = serializers.CharField()
    reasons = AwardRiskReasonSerializer(many=True)


class AwardRiskResponseSerializer(serializers.Serializer):
    tenderId = serializers.CharField()
    baseline = serializers.DictField()
    participants = AwardRiskParticipantSerializer(many=True)
    generatedAt = serializers.DateTimeField()
