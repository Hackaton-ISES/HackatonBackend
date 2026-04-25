from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from tenders.models import Company, RiskReason, Tender, TenderBid, TenderRiskAnalysis, UserProfile


class TenderBidInline(TabularInline):
    model = TenderBid
    extra = 0
    autocomplete_fields = ('company',)
    fields = ('company', 'bid_price', 'is_winner', 'created_at')
    readonly_fields = ('created_at',)


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


@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):
    list_display = ('user', 'role', 'company', 'created_at')
    list_filter = ('role',)
    search_fields = ('user__username', 'company__name')
    readonly_fields = ('created_at', 'updated_at')


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
    inlines = (TenderBidInline,)


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
        'fake_competition_score',
        'analyzed_at',
    )
    list_filter = ('risk_level',)
    search_fields = (
        'tender__title',
        'tender__organization',
        'tender__winner_company__name',
    )
    readonly_fields = ('analyzed_at', 'ai_summary')


@admin.register(RiskReason)
class RiskReasonAdmin(ModelAdmin):
    list_display = ('title', 'analysis', 'score', 'created_at')
    list_filter = ('score', 'analysis__risk_level')
    search_fields = ('title', 'description', 'analysis__tender__title')
    readonly_fields = ('created_at',)


@admin.register(TenderBid)
class TenderBidAdmin(ModelAdmin):
    list_display = ('tender', 'company', 'bid_price', 'is_winner', 'created_at')
    list_filter = ('is_winner', 'tender__organization', 'tender__category')
    search_fields = ('tender__title', 'company__name')
    readonly_fields = ('created_at',)
