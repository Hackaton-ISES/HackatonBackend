from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Count

from tenders.models import Company, CompanySuspicionAnalysis, CompanySuspicionReason, Tender
from tenders.services.gemini_summary import generate_company_summary


ZERO = Decimal('0')
TWO = Decimal('2')
HUNDRED = Decimal('100')


@dataclass(frozen=True)
class ScoreReason:
    title: str
    description: str
    score: int


@dataclass(frozen=True)
class ScoreResult:
    score: int
    reasons: list[ScoreReason]


def calculate_price_score(company: Company) -> ScoreResult:
    suspicious_tenders: list[tuple[str, Decimal, int]] = []
    score = 0

    won_tenders = company.won_tenders.exclude(status=Tender.Status.CANCELLED)
    for tender in won_tenders:
        difference = tender.price_difference_percent
        tender_score = 0
        if difference > Decimal('50'):
            tender_score = 20
        elif difference > Decimal('35'):
            tender_score = 15
        elif difference > Decimal('20'):
            tender_score = 10
        elif difference > Decimal('10'):
            tender_score = 5

        if tender_score:
            score += tender_score
            suspicious_tenders.append((tender.title, difference, tender_score))

        if tender.budget > ZERO and tender.final_price == tender.budget:
            score += 5
            suspicious_tenders.append((tender.title, Decimal('0.00'), 5))

    score = min(score, 35)
    if score == 0:
        return ScoreResult(score=0, reasons=[])

    examples = ', '.join(
        f'{title} ({difference}% -> {tender_score})'
        for title, difference, tender_score in suspicious_tenders[:3]
    )
    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Winner price anomaly',
                description=(
                    f'{company.name} won tenders with suspicious market-price gaps or exact-budget matches. '
                ),
                score=score,
            )
        ],
    )


def calculate_failed_delivery_score(company: Company) -> ScoreResult:
    failed_wins = list(
        company.won_tenders.filter(
            status=Tender.Status.COMPLETED,
            is_completed_by_winner=False,
        ).values_list('title', flat=True)
    )
    failed_count = len(failed_wins)
    if failed_count == 0:
        return ScoreResult(score=0, reasons=[])

    score = min(failed_count * 20, 40)
    examples = ', '.join(failed_wins[:3])
    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Failed delivery after winning',
                description=(
                    f'{company.name} won {failed_count} tender(s) that were not completed by the winner. '
                ),
                score=score,
            )
        ],
    )


def _max_consecutive_win_streak(company: Company) -> tuple[int, str, str]:
    max_streak = 0
    max_organization = ''
    max_category = ''

    grouped: dict[tuple[str, str], list[Tender]] = defaultdict(list)
    for tender in Tender.objects.exclude(status=Tender.Status.CANCELLED).order_by('created_at', 'id'):
        grouped[(tender.organization, tender.category)].append(tender)

    for (organization, category), tenders in grouped.items():
        streak = 0
        for tender in tenders:
            if tender.winner_company_id == company.id:
                streak += 1
                if streak > max_streak:
                    max_streak = streak
                    max_organization = organization
                    max_category = category
            else:
                streak = 0
    return max_streak, max_organization, max_category


def calculate_consecutive_wins_score(company: Company) -> ScoreResult:
    streak, organization, category = _max_consecutive_win_streak(company)
    if streak < 3:
        return ScoreResult(score=0, reasons=[])

    if streak >= 5:
        score = 30
    elif streak == 4:
        score = 20
    else:
        score = 10

    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Consecutive wins pattern',
                description=(
                    f'{company.name} won {streak} consecutive tenders for {organization} in {category}. '
                ),
                score=score,
            )
        ],
    )


def _participant_overlap_ratio(current_ids: set[int], previous_ids: set[int]) -> Decimal:
    if not current_ids or not previous_ids:
        return ZERO
    denominator = max(len(current_ids), len(previous_ids))
    if denominator == 0:
        return ZERO
    return (Decimal(len(current_ids & previous_ids)) / Decimal(denominator)) * HUNDRED


def _repeated_same_participants_check(company: Company) -> ScoreResult:
    suspicious_count = 0
    for tender in company.won_tenders.exclude(status=Tender.Status.CANCELLED).prefetch_related('participants'):
        current_ids = set(tender.participants.values_list('id', flat=True))
        if len(current_ids) < 2:
            continue
        previous_tenders = (
            Tender.objects.filter(
                organization=tender.organization,
                category=tender.category,
                created_at__lt=tender.created_at,
            )
            .exclude(status=Tender.Status.CANCELLED)
            .prefetch_related('participants')
        )
        for previous in previous_tenders:
            previous_ids = set(previous.participants.values_list('id', flat=True))
            if _participant_overlap_ratio(current_ids, previous_ids) >= Decimal('70'):
                suspicious_count += 1

    if suspicious_count < 4:
        return ScoreResult(score=0, reasons=[])

    score = 20 if suspicious_count >= 6 else 10
    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Repeated same participants',
                description=(
                    f'{company.name} appears in repeated tender groups with at least 70% participant overlap '
                ),
                score=score,
            )
        ],
    )


def _close_prices_check(company: Company) -> ScoreResult:
    suspicious_tenders = 0
    for tender in company.won_tenders.exclude(status=Tender.Status.CANCELLED).prefetch_related('bids__company'):
        bids = list(tender.bids.order_by('bid_price', 'id'))
        winner_bid = next((bid for bid in bids if bid.company_id == company.id), None)
        if winner_bid is None or winner_bid.bid_price <= ZERO:
            continue
        close_losers = 0
        for bid in bids:
            if bid.pk == winner_bid.pk:
                continue
            gap_percent = ((bid.bid_price - winner_bid.bid_price) / winner_bid.bid_price) * HUNDRED
            if gap_percent.copy_abs() <= TWO:
                close_losers += 1
        if close_losers >= 2:
            suspicious_tenders += 1

    if suspicious_tenders == 0:
        return ScoreResult(score=0, reasons=[])

    score = 20 if suspicious_tenders >= 4 else 10
    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Very close bid prices',
                description=(
                    f'{company.name} has {suspicious_tenders} winning tender(s) where losing bids were within 1-2% '
                ),
                score=score,
            )
        ],
    )


def _same_winner_same_losers_check(company: Company) -> ScoreResult:
    pattern_counter: Counter[tuple[int, ...]] = Counter()
    for tender in company.won_tenders.exclude(status=Tender.Status.CANCELLED).prefetch_related('participants'):
        loser_ids = tuple(sorted(tender.participants.exclude(id=company.id).values_list('id', flat=True)))
        if loser_ids:
            pattern_counter[loser_ids] += 1

    repeated_patterns = max(pattern_counter.values(), default=0)
    if repeated_patterns < 4:
        return ScoreResult(score=0, reasons=[])

    score = 25 if repeated_patterns >= 5 else 15
    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Repeated winner-loser pattern',
                description=(
                    f'{company.name} appeared with the same losing companies in {repeated_patterns} tender(s). '
                ),
                score=score,
            )
        ],
    )


def calculate_fake_competition_score(company: Company) -> ScoreResult:
    results = [
        _repeated_same_participants_check(company),
        _close_prices_check(company),
        _same_winner_same_losers_check(company),
    ]
    return ScoreResult(
        score=min(sum(result.score for result in results), 35),
        reasons=[reason for result in results for reason in result.reasons],
    )


@transaction.atomic
def analyze_company(company: Company) -> CompanySuspicionAnalysis:
    company = Company.objects.get(pk=company.pk)
    company.update_statistics()
    analysis, _ = CompanySuspicionAnalysis.objects.get_or_create(company=company)
    analysis.reasons.all().delete()

    price_result = calculate_price_score(company)
    failed_delivery_result = calculate_failed_delivery_score(company)
    consecutive_result = calculate_consecutive_wins_score(company)
    fake_competition_result = calculate_fake_competition_score(company)

    analysis.price_score = price_result.score
    analysis.failed_delivery_score = failed_delivery_result.score
    analysis.consecutive_wins_score = consecutive_result.score
    analysis.fake_competition_score = fake_competition_result.score
    analysis.ai_summary = ''
    analysis.save()

    all_reasons = (
        price_result.reasons
        + failed_delivery_result.reasons
        + consecutive_result.reasons
        + fake_competition_result.reasons
    )
    CompanySuspicionReason.objects.bulk_create(
        [
            CompanySuspicionReason(
                analysis=analysis,
                title=reason.title,
                description=reason.description,
                score=reason.score,
            )
            for reason in all_reasons
        ]
    )
    analysis = CompanySuspicionAnalysis.objects.prefetch_related('reasons').get(pk=analysis.pk)
    analysis.ai_summary = generate_company_summary(company=company, analysis=analysis)
    if analysis.ai_summary:
        analysis.save(update_fields=['ai_summary', 'analyzed_at'])
    return CompanySuspicionAnalysis.objects.prefetch_related('reasons').get(pk=analysis.pk)


def analyze_all_companies() -> None:
    for company in Company.objects.all().order_by('id'):
        analyze_company(company)


def get_company_stats():
    distribution = {
        item['suspicion_level']: item['count']
        for item in CompanySuspicionAnalysis.objects.values('suspicion_level').annotate(count=Count('id'))
    }
    top_companies = [
        {
            'companyId': analysis.company.external_id,
            'companyName': analysis.company.name,
            'totalScore': analysis.total_score,
            'suspicionLevel': analysis.suspicion_level.upper(),
        }
        for analysis in CompanySuspicionAnalysis.objects.select_related('company').order_by(
            '-total_score', 'company__name'
        )[:5]
    ]
    return {
        'total': Company.objects.count(),
        'high': distribution.get('high', 0),
        'medium': distribution.get('medium', 0),
        'low': distribution.get('low', 0),
        'distribution': {
            'HIGH': distribution.get('high', 0),
            'MEDIUM': distribution.get('medium', 0),
            'LOW': distribution.get('low', 0),
        },
        'top_suspicious_companies': top_companies,
        'total_analyzed_companies': CompanySuspicionAnalysis.objects.count(),
    }
