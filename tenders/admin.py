from django.contrib import admin
from unfold.admin import ModelAdmin

from tenders.models import Company, RiskReason, Tender, TenderRiskAnalysis


@admin.register(Company)
class CompanyAdmin(ModelAdmin):
    list_display = (
        'name',
        'total_participations',
        'total_wins',
        'completed_projects',
        'failed_projects',
        'win_rate',
        'failure_rate',
    )
    search_fields = ('name',)
    ordering = ('name',)


@admin.register(Tender)
class TenderAdmin(ModelAdmin):
    list_display = (
        'title',
        'organization',
        'category',
        'winner_company',
        'final_price',
        'average_market_price',
        'price_difference_percent',
        'status',
        'created_at',
        'deadline',
    )
    list_filter = ('status', 'category', 'organization')
    search_fields = ('title', 'organization', 'winner_company__name')
    filter_horizontal = ('participants',)
    readonly_fields = ('added_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(TenderRiskAnalysis)
class TenderRiskAnalysisAdmin(ModelAdmin):
    list_display = (
        'tender',
        'total_score',
        'risk_level',
        'price_score',
        'company_history_score',
        'consecutive_wins_score',
        'participants_score',
        'analyzed_at',
    )
    list_filter = ('risk_level',)
    search_fields = (
        'tender__title',
        'tender__organization',
        'tender__winner_company__name',
    )
    readonly_fields = ('analyzed_at',)


@admin.register(RiskReason)
class RiskReasonAdmin(ModelAdmin):
    list_display = ('title', 'analysis', 'score', 'created_at')
    search_fields = ('title', 'description', 'analysis__tender__title')
    readonly_fields = ('created_at',)
