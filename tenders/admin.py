from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from tenders.forms import CompanyAdminForm
from tenders.models import (
    Company,
    CompanySuspicionAnalysis,
    CompanySuspicionReason,
    Tender,
    TenderAuditApproval,
    TenderBid,
    UserProfile,
)
from tenders.services.account_creation import create_company_account


class TenderBidInline(TabularInline):
    model = TenderBid
    extra = 0
    autocomplete_fields = ('company',)
    fields = ('company', 'bid_price', 'is_winner', 'created_at')
    readonly_fields = ('company', 'bid_price', 'is_winner', 'created_at')
    can_delete = False


@admin.register(Company)
class CompanyAdmin(ModelAdmin):
    form = CompanyAdminForm
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

    fieldsets = (
        (None, {'fields': ('name',)}),
        (
            'Account Setup',
            {
                'fields': ('username', 'password', 'email', 'first_name', 'last_name'),
                'description': 'Create the login account together with the company on the add form.',
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return

        user = create_company_account(
            company_name=form.cleaned_data['name'],
            username=form.cleaned_data['username'],
            password=form.cleaned_data['password'],
            email=form.cleaned_data.get('email', ''),
            first_name=form.cleaned_data.get('first_name', ''),
            last_name=form.cleaned_data.get('last_name', ''),
        )
        company = user.profile.company
        obj.pk = company.pk
        obj.external_id = company.external_id
        obj.created_at = company.created_at
        obj.updated_at = company.updated_at
        obj._state.adding = False


@admin.register(CompanySuspicionAnalysis)
class CompanySuspicionAnalysisAdmin(ModelAdmin):
    list_display = (
        'company',
        'total_score',
        'suspicion_level',
        'price_score',
        'failed_delivery_score',
        'consecutive_wins_score',
        'fake_competition_score',
        'analyzed_at',
    )
    list_filter = ('suspicion_level',)
    search_fields = ('company__name',)
    readonly_fields = ('analyzed_at',)


@admin.register(CompanySuspicionReason)
class CompanySuspicionReasonAdmin(ModelAdmin):
    list_display = ('title', 'analysis', 'score', 'created_at')
    list_filter = ('score', 'analysis__suspicion_level')
    search_fields = ('title', 'description', 'analysis__company__name')
    readonly_fields = ('created_at',)


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
    readonly_fields = (
        'created_at',
        'final_price',
        'participants',
        'participants_count',
        'winner_company',
        'status',
        'is_completed_by_winner',
        'added_at',
        'updated_at',
    )
    ordering = ('-created_at',)
    inlines = (TenderBidInline,)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.winner_company_id:
            readonly_fields.extend(
                [
                    'title',
                    'organization',
                    'category',
                    'budget',
                    'average_market_price',
                    'deadline',
                ]
            )
        return tuple(readonly_fields)

    def get_inline_instances(self, request, obj=None):
        if obj and obj.winner_company_id:
            return []
        return super().get_inline_instances(request, obj)

@admin.register(TenderBid)
class TenderBidAdmin(ModelAdmin):
    list_display = ('tender', 'company', 'bid_price', 'is_winner', 'created_at')
    list_filter = ('is_winner', 'tender__organization', 'tender__category')
    search_fields = ('tender__title', 'company__name')
    readonly_fields = ('created_at',)


@admin.register(TenderAuditApproval)
class TenderAuditApprovalAdmin(ModelAdmin):
    list_display = ('tender', 'application', 'approved_by', 'created_at')
    search_fields = ('tender__title', 'application__external_id', 'application__company__name', 'approved_by__username')
    readonly_fields = ('created_at',)
