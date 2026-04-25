from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from tenders.models import Company, RiskReason, Tender, TenderBid, TenderRiskAnalysis, UserProfile, ensure_user_profile
from tenders.services.risk_scoring import analyze_tender


class CompanySerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='external_id', read_only=True)

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
        ]


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
        company = Company.objects.create(name=validated_data['company_name'])
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        UserProfile.objects.create(
            user=user,
            role=UserProfile.Role.COMPANY,
            company=company,
            external_id=company.external_id,
        )
        return user


class TenderBidSerializer(serializers.ModelSerializer):
    company = CompanySerializer(read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = TenderBid
        fields = ['external_id', 'company', 'bid_price', 'is_winner', 'status', 'created_at']


class RiskReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskReason
        fields = ['id', 'title', 'description', 'score', 'created_at']


class RiskFlagSerializer(serializers.Serializer):
    severity = serializers.ChoiceField(choices=['warning', 'critical'])
    message = serializers.CharField()


class TenderRiskAnalysisSerializer(serializers.ModelSerializer):
    reasons = RiskReasonSerializer(many=True, read_only=True)

    class Meta:
        model = TenderRiskAnalysis
        fields = [
            'total_score',
            'risk_level',
            'price_score',
            'company_history_score',
            'consecutive_wins_score',
            'participants_score',
            'fake_competition_score',
            'ai_summary',
            'analyzed_at',
            'reasons',
        ]


class RiskStatsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    high = serializers.IntegerField()
    medium = serializers.IntegerField()
    low = serializers.IntegerField()
    distribution = serializers.DictField(child=serializers.IntegerField())
    top_risky_organizations = serializers.ListField(child=serializers.DictField())
    total_analyzed_tenders = serializers.IntegerField()


class TenderAnalysisSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='external_id', read_only=True)
    participantsCount = serializers.SerializerMethodField()
    averageMarketPrice = serializers.DecimalField(source='average_market_price', max_digits=14, decimal_places=2, read_only=True)
    finalPrice = serializers.DecimalField(source='final_price', max_digits=14, decimal_places=2, read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    riskScore = serializers.SerializerMethodField()
    riskLevel = serializers.SerializerMethodField()
    riskFlags = serializers.SerializerMethodField()
    winnerCompanyId = serializers.SerializerMethodField()

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
            'status',
            'createdAt',
            'deadline',
            'riskScore',
            'riskLevel',
            'riskFlags',
        ]

    def _get_analysis(self, obj: Tender) -> TenderRiskAnalysis | None:
        if not hasattr(obj, '_analysis_cache'):
            try:
                obj._analysis_cache = obj.risk_analysis
            except TenderRiskAnalysis.DoesNotExist:
                if self.context.get('auto_analyze', False):
                    obj._analysis_cache = analyze_tender(obj)
                else:
                    obj._analysis_cache = None
        return obj._analysis_cache

    @extend_schema_field(serializers.IntegerField)
    def _build_flags(self, obj):
        analysis = self._get_analysis(obj)
        if analysis is None:
            return []
        reasons = analysis.reasons.all()
        return [
            {
                'severity': 'critical' if reason.score >= 15 else 'warning',
                'message': reason.description,
            }
            for reason in reasons
        ]

    @extend_schema_field(serializers.IntegerField)
    def get_riskScore(self, obj):
        analysis = self._get_analysis(obj)
        return analysis.total_score if analysis else 0

    @extend_schema_field(serializers.CharField)
    def get_riskLevel(self, obj):
        analysis = self._get_analysis(obj)
        return analysis.risk_level.upper() if analysis else 'LOW'

    @extend_schema_field(RiskFlagSerializer(many=True))
    def get_riskFlags(self, obj):
        return self._build_flags(obj)

    @extend_schema_field(serializers.IntegerField)
    def get_participantsCount(self, obj):
        return obj.get_actual_participants_count()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_winnerCompanyId(self, obj):
        return obj.winner_company.external_id if obj.winner_company else None


class TenderDetailSerializer(TenderAnalysisSerializer):
    riskAnalysis = serializers.SerializerMethodField()
    reasons = serializers.SerializerMethodField()
    bids = serializers.SerializerMethodField()

    class Meta(TenderAnalysisSerializer.Meta):
        fields = TenderAnalysisSerializer.Meta.fields + ['riskAnalysis', 'reasons', 'bids']

    @extend_schema_field(TenderRiskAnalysisSerializer)
    def get_riskAnalysis(self, obj):
        analysis = self._get_analysis(obj)
        if analysis is None:
            return None
        return TenderRiskAnalysisSerializer(analysis).data

    @extend_schema_field(RiskReasonSerializer(many=True))
    def get_reasons(self, obj):
        analysis = self._get_analysis(obj)
        if analysis is None:
            return []
        return RiskReasonSerializer(analysis.reasons.all(), many=True).data

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
        tender = Tender.objects.create(
            participants_count=0,
            status=Tender.Status.ACTIVE,
            is_completed_by_winner=None,
            winner_company=None,
            **validated_data,
        )
        analyze_tender(tender)
        return tender


class TenderWriteSerializer(serializers.ModelSerializer):
    participant_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Company.objects.all(),
        write_only=True,
        source='participants',
        required=False,
    )
    winner_company_id = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        write_only=True,
        source='winner_company',
        allow_null=True,
        required=False,
    )
    bids = serializers.ListField(child=serializers.DictField(), write_only=True, required=False)
    risk_analysis = serializers.SerializerMethodField(read_only=True)
    reasons = serializers.SerializerMethodField(read_only=True)

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
            'participant_ids',
            'participants_count',
            'winner_company_id',
            'status',
            'created_at',
            'deadline',
            'added_at',
            'updated_at',
            'bids',
            'risk_analysis',
            'reasons',
        ]
        read_only_fields = [
            'id',
            'participants_count',
            'added_at',
            'updated_at',
            'risk_analysis',
            'reasons',
        ]

    def validate(self, attrs):
        participants = attrs.get('participants')
        winner_company = attrs.get('winner_company')
        created_at = attrs.get('created_at', getattr(self.instance, 'created_at', None))
        deadline = attrs.get('deadline', getattr(self.instance, 'deadline', None))

        if participants is None and self.instance is not None:
            participants = list(self.instance.participants.all())
        elif participants is None:
            participants = []

        if participants and winner_company and winner_company not in participants:
            raise serializers.ValidationError(
                {'winner_company_id': 'Winner company must be one of the participants.'}
            )
        if not participants and winner_company:
            raise serializers.ValidationError(
                {'winner_company_id': 'Winner company cannot be set before participants join the tender.'}
            )

        if created_at and deadline and deadline <= created_at:
            raise serializers.ValidationError({'deadline': 'Deadline must be later than created_at.'})
        return attrs

    def _replace_bids(self, tender: Tender, bids_payload: list[dict]) -> None:
        if bids_payload is None:
            return
        tender.bids.all().delete()
        for bid_item in bids_payload:
            company_id = bid_item.get('company_id')
            if company_id is None:
                continue
            TenderBid.objects.create(
                tender=tender,
                company_id=company_id,
                bid_price=bid_item['bid_price'],
                is_winner=bid_item.get('is_winner', False),
            )

    @transaction.atomic
    def create(self, validated_data):
        participants = list(validated_data.pop('participants', []))
        bids_payload = validated_data.pop('bids', [])
        tender = Tender.objects.create(participants_count=len(participants), **validated_data)
        tender.participants.set(participants)
        self._replace_bids(tender, bids_payload)
        for participant in participants:
            participant.update_statistics()
        if tender.winner_company:
            tender.winner_company.update_statistics()
        analyze_tender(tender)
        return tender

    @transaction.atomic
    def update(self, instance, validated_data):
        participants = validated_data.pop('participants', None)
        bids_payload = validated_data.pop('bids', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if participants is not None:
            participants = list(participants)
            instance.participants_count = len(participants)
        instance.save()
        if participants is not None:
            instance.participants.set(participants)
            for participant in participants:
                participant.update_statistics()
        self._replace_bids(instance, bids_payload)
        if instance.winner_company:
            instance.winner_company.update_statistics()
        analyze_tender(instance)
        return instance

    @extend_schema_field(TenderRiskAnalysisSerializer)
    def get_risk_analysis(self, obj):
        return TenderRiskAnalysisSerializer(analyze_tender(obj)).data

    @extend_schema_field(RiskReasonSerializer(many=True))
    def get_reasons(self, obj):
        return RiskReasonSerializer(analyze_tender(obj).reasons.all(), many=True).data


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
        application.company.update_statistics()
        analyze_tender(application.tender)
        return application


class ApplicationStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['won', 'lost'])


class FrontendApplicationSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='external_id', read_only=True)
    tenderId = serializers.CharField(source='tender.external_id', read_only=True)
    companyId = serializers.CharField(source='company.external_id', read_only=True)
    companyName = serializers.CharField(source='company.name', read_only=True)
    proposedPrice = serializers.DecimalField(source='bid_price', max_digits=14, decimal_places=2, read_only=True)
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
    proposedPrice = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    productName = serializers.CharField(min_length=1, max_length=120)
    productDescription = serializers.CharField(min_length=1, max_length=1000)


class AnalyzeTenderResponseSerializer(serializers.ModelSerializer):
    tenderId = serializers.CharField(source='tender.external_id', read_only=True)
    totalScore = serializers.IntegerField(source='total_score', read_only=True)
    riskLevel = serializers.SerializerMethodField()
    riskFlags = serializers.SerializerMethodField()

    class Meta:
        model = TenderRiskAnalysis
        fields = [
            'tenderId',
            'totalScore',
            'riskLevel',
            'price_score',
            'company_history_score',
            'consecutive_wins_score',
            'participants_score',
            'fake_competition_score',
            'ai_summary',
            'riskFlags',
        ]

    @extend_schema_field(serializers.CharField)
    def get_riskLevel(self, obj):
        return obj.risk_level.upper()

    @extend_schema_field(RiskFlagSerializer(many=True))
    def get_riskFlags(self, obj):
        return [
            {
                'severity': 'critical' if reason.score >= 15 else 'warning',
                'message': reason.description,
            }
            for reason in obj.reasons.all()
        ]
