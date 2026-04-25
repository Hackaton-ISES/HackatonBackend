from django.db import transaction
from rest_framework import serializers

from tenders.models import Company, Tender
from tenders.services.risk_analysis import analyze_tender_risk


class CompanySerializer(serializers.ModelSerializer):
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


class TenderAnalysisSerializer(serializers.ModelSerializer):
    participants = CompanySerializer(many=True, read_only=True)
    winner_company = CompanySerializer(read_only=True)
    risk_score = serializers.SerializerMethodField()
    risk_level = serializers.SerializerMethodField()
    reasons = serializers.SerializerMethodField()

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
            'participants_count',
            'participants',
            'winner_company',
            'status',
            'is_completed_by_winner',
            'created_at',
            'deadline',
            'added_at',
            'updated_at',
            'risk_score',
            'risk_level',
            'reasons',
        ]

    def _get_analysis(self, obj):
        if not hasattr(obj, '_risk_analysis'):
            obj._risk_analysis = analyze_tender_risk(obj)
        return obj._risk_analysis

    def get_risk_score(self, obj):
        return self._get_analysis(obj).risk_score

    def get_risk_level(self, obj):
        return self._get_analysis(obj).risk_level

    def get_reasons(self, obj):
        return self._get_analysis(obj).reasons


class TenderCreateSerializer(serializers.ModelSerializer):
    participant_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Company.objects.all(),
        write_only=True,
        source='participants',
    )
    winner_company_id = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        write_only=True,
        source='winner_company',
        allow_null=True,
        required=False,
    )
    risk_score = serializers.SerializerMethodField(read_only=True)
    risk_level = serializers.SerializerMethodField(read_only=True)
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
            'is_completed_by_winner',
            'created_at',
            'deadline',
            'added_at',
            'updated_at',
            'risk_score',
            'risk_level',
            'reasons',
        ]
        read_only_fields = [
            'id',
            'participants_count',
            'added_at',
            'updated_at',
            'risk_score',
            'risk_level',
            'reasons',
        ]

    def validate(self, attrs):
        participants = attrs.get('participants', [])
        winner_company = attrs.get('winner_company')
        created_at = attrs.get('created_at')
        deadline = attrs.get('deadline')

        if not participants:
            raise serializers.ValidationError(
                {'participant_ids': 'At least one participant is required.'}
            )

        if winner_company and winner_company not in participants:
            raise serializers.ValidationError(
                {'winner_company_id': 'Winner company must be one of the participants.'}
            )

        if deadline <= created_at:
            raise serializers.ValidationError(
                {'deadline': 'Deadline must be later than created_at.'}
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        participants = list(validated_data.pop('participants', []))
        tender = Tender.objects.create(
            participants_count=len(participants),
            **validated_data,
        )
        tender.participants.set(participants)

        # Keep aggregate counters in sync for the MVP dataset.
        for participant in participants:
            participant.total_participations += 1
            participant.save(update_fields=['total_participations'])

        winner_company = tender.winner_company
        if winner_company:
            winner_company.total_wins += 1
            winner_company.save(update_fields=['total_wins'])

        return tender

    def _get_analysis(self, obj):
        if not hasattr(obj, '_risk_analysis'):
            obj._risk_analysis = analyze_tender_risk(obj)
        return obj._risk_analysis

    def get_risk_score(self, obj):
        return self._get_analysis(obj).risk_score

    def get_risk_level(self, obj):
        return self._get_analysis(obj).risk_level

    def get_reasons(self, obj):
        return self._get_analysis(obj).reasons
