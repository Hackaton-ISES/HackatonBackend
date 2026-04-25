from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Count

from tenders.models import RiskReason, Tender, TenderBid, TenderRiskAnalysis
from tenders.services.gemini_summary import generate_risk_summary


ZERO = Decimal('0')
TWO = Decimal('2')
THREE = Decimal('3')
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


def calculate_price_score(tender: Tender) -> ScoreResult:
    score = 0
    reasons: list[ScoreReason] = []
    difference_percent = tender.price_difference_percent

    market_score = 0
    if difference_percent > Decimal('50'):
        market_score = 40
    elif difference_percent > Decimal('35'):
        market_score = 30
    elif difference_percent > Decimal('20'):
        market_score = 20
    elif difference_percent > Decimal('10'):
        market_score = 10

    if market_score:
        score += market_score
        reasons.append(
            ScoreReason(
                title='Price comparison risk',
                description=(
                    f'Final price {tender.final_price} vs market average '
                    f'{tender.average_market_price} produced a {difference_percent}% increase. '
                    f'Score added: {market_score}.'
                ),
                score=market_score,
            )
        )

    if tender.final_price == tender.budget:
        score += 10
        reasons.append(
            ScoreReason(
                title='Suspicious exact budget match',
                description=(
                    f'Final price exactly matches the budget at {tender.budget}. Score added: 10.'
                ),
                score=10,
            )
        )

    if tender.final_price > tender.budget and tender.budget > ZERO:
        overrun_percent = tender.budget_difference_percent
        overrun_score = 0
        if overrun_percent > Decimal('20'):
            overrun_score = 15
        elif overrun_percent > Decimal('10'):
            overrun_score = 10
        if overrun_score:
            score += overrun_score
            reasons.append(
                ScoreReason(
                    title='Budget overrun risk',
                    description=(
                        f'Final price exceeds budget by {overrun_percent}%. '
                        f'Score added: {overrun_score}.'
                    ),
                    score=overrun_score,
                )
            )

    return ScoreResult(score=min(score, 50), reasons=reasons)


def calculate_company_history_score(tender: Tender) -> ScoreResult:
    winner = tender.winner_company
    if winner is None or winner.total_wins == 0:
        return ScoreResult(score=0, reasons=[])

    failure_rate = winner.failure_rate
    score = 0
    if failure_rate > Decimal('50'):
        score = 30
    elif failure_rate > Decimal('30'):
        score = 20
    elif failure_rate > Decimal('10'):
        score = 10

    if score == 0:
        return ScoreResult(score=0, reasons=[])

    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Company execution history risk',
                description=(
                    f'{winner.name} has {winner.total_wins} total wins, '
                    f'{winner.completed_projects} completed projects, {winner.failed_projects} failed projects, '
                    f'and a {failure_rate}% failure rate. Score added: {score}.'
                ),
                score=score,
            )
        ],
    )


def _consecutive_wins_count(tender: Tender) -> int:
    if tender.winner_company_id is None:
        return 0

    matching_tenders = (
        Tender.objects.filter(
            organization=tender.organization,
            category=tender.category,
            created_at__lte=tender.created_at,
        )
        .exclude(status=Tender.Status.CANCELLED)
        .select_related('winner_company')
        .order_by('created_at', 'id')
    )

    current_streak = 0
    previous_winner_id = None
    for item in matching_tenders:
        if item.winner_company_id and item.winner_company_id == previous_winner_id:
            current_streak += 1
        elif item.winner_company_id:
            current_streak = 1
        else:
            current_streak = 0

        previous_winner_id = item.winner_company_id
        if item.pk == tender.pk:
            return current_streak if item.winner_company_id == tender.winner_company_id else 0
    return 0


def calculate_consecutive_wins_score(tender: Tender) -> ScoreResult:
    if tender.winner_company is None:
        return ScoreResult(score=0, reasons=[])

    streak = _consecutive_wins_count(tender)
    score = 0
    reasons: list[ScoreReason] = []

    if streak >= 5:
        score += 30
    elif streak == 4:
        score += 20
    elif streak == 3:
        score += 10

    if score:
        reasons.append(
            ScoreReason(
                title='Consecutive wins risk',
                description=(
                    f'{tender.winner_company.name} has won {streak} consecutive tenders '
                    f'for {tender.organization} in category {tender.category}. '
                    f'Score added: {score}.'
                ),
                score=score,
            )
        )

    organization_win_count = Tender.objects.filter(
        organization=tender.organization,
        winner_company=tender.winner_company,
    ).exclude(status=Tender.Status.CANCELLED).count()
    if organization_win_count >= 4:
        reasons.append(
            ScoreReason(
                title='Winner repetition per organization',
                description=(
                    f'{tender.winner_company.name} has won {organization_win_count} tenders '
                    f'from {tender.organization}. Score added: 10.'
                ),
                score=10,
            )
        )
        score += 10

    return ScoreResult(score=min(score, 40), reasons=reasons)


def calculate_participants_score(tender: Tender) -> ScoreResult:
    score = 0
    reasons: list[ScoreReason] = []

    if tender.get_actual_participants_count() <= 1:
        score += 15
        reasons.append(
            ScoreReason(
                title='Single bidder risk',
                description='Only one bidder participated in this tender. Score added: 15.',
                score=15,
            )
        )

    submission_window_days = Decimal(str((tender.deadline - tender.created_at).total_seconds())) / Decimal('86400')
    if submission_window_days < THREE:
        score += 10
        reasons.append(
            ScoreReason(
                title='Very short deadline risk',
                description=(
                    f'The tender submission window was {submission_window_days.quantize(Decimal("0.01"))} days. '
                    'Score added: 10.'
                ),
                score=10,
            )
        )

    late_bid_count = tender.bids.filter(created_at__gt=tender.deadline).count()
    if late_bid_count:
        late_score = 10 if late_bid_count <= 2 else 15
        score += late_score
        reasons.append(
            ScoreReason(
                title='Late bid submissions risk',
                description=(
                    f'{late_bid_count} bids were submitted after the deadline. '
                    f'Score added: {late_score}.'
                ),
                score=late_score,
            )
        )

    return ScoreResult(score=min(score, 30), reasons=reasons)


def _participant_overlap_ratio(current_ids: set[int], previous_ids: set[int]) -> Decimal:
    if not current_ids or not previous_ids:
        return ZERO
    denominator = max(len(current_ids), len(previous_ids))
    if denominator == 0:
        return ZERO
    return (Decimal(len(current_ids & previous_ids)) / Decimal(denominator)) * HUNDRED


def _repeated_same_participants_check(tender: Tender) -> ScoreResult:
    current_ids = set(tender.participants.values_list('id', flat=True))
    if len(current_ids) < 2:
        return ScoreResult(score=0, reasons=[])

    similar_count = 0
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
            similar_count += 1

    score = 0
    if similar_count >= 6:
        score = 20
    elif similar_count >= 4:
        score = 10
    if score == 0:
        return ScoreResult(score=0, reasons=[])

    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Repeated same participants risk',
                description=(
                    f'{similar_count} previous tenders in {tender.organization} / {tender.category} '
                    f'had at least 70% participant overlap. Score added: {score}.'
                ),
                score=score,
            )
        ],
    )


def _close_prices_check(tender: Tender) -> ScoreResult:
    bids = list(tender.bids.select_related('company').order_by('bid_price', 'id'))
    if len(bids) < 3:
        return ScoreResult(score=0, reasons=[])

    winner_bid = next((bid for bid in bids if bid.is_winner), None)
    if winner_bid is None and tender.winner_company_id:
        winner_bid = next((bid for bid in bids if bid.company_id == tender.winner_company_id), None)
    if winner_bid is None or winner_bid.bid_price <= ZERO:
        return ScoreResult(score=0, reasons=[])

    close_losers = 0
    for bid in bids:
        if bid.pk == winner_bid.pk:
            continue
        gap_percent = ((bid.bid_price - winner_bid.bid_price) / winner_bid.bid_price) * HUNDRED
        if gap_percent.copy_abs() <= TWO:
            close_losers += 1

    score = 0
    if close_losers >= 3:
        score = 20
    elif close_losers >= 2:
        score = 15
    if score == 0:
        return ScoreResult(score=0, reasons=[])

    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Very close prices risk',
                description=(
                    f'{close_losers} losing bids were within 2% of the winning bid '
                    f'{winner_bid.bid_price}. Score added: {score}.'
                ),
                score=score,
            )
        ],
    )


def _same_winner_same_losers_check(tender: Tender) -> ScoreResult:
    if tender.winner_company_id is None:
        return ScoreResult(score=0, reasons=[])

    current_loser_ids = set(
        tender.participants.exclude(id=tender.winner_company_id).values_list('id', flat=True)
    )
    if not current_loser_ids:
        return ScoreResult(score=0, reasons=[])

    repeated_patterns = 0
    previous_tenders = (
        Tender.objects.filter(
            winner_company=tender.winner_company,
            created_at__lt=tender.created_at,
        )
        .exclude(status=Tender.Status.CANCELLED)
        .prefetch_related('participants')
    )
    for previous in previous_tenders:
        previous_loser_ids = set(
            previous.participants.exclude(id=tender.winner_company_id).values_list('id', flat=True)
        )
        if previous_loser_ids == current_loser_ids:
            repeated_patterns += 1

    score = 0
    if repeated_patterns >= 6:
        score = 25
    elif repeated_patterns >= 4:
        score = 15
    if score == 0:
        return ScoreResult(score=0, reasons=[])

    return ScoreResult(
        score=score,
        reasons=[
            ScoreReason(
                title='Repeated winner and losers risk',
                description=(
                    f'The same winner and losing companies pattern appeared {repeated_patterns} times. '
                    f'Score added: {score}.'
                ),
                score=score,
            )
        ],
    )


def calculate_fake_competition_score(tender: Tender) -> ScoreResult:
    results = [
        _repeated_same_participants_check(tender),
        _close_prices_check(tender),
        _same_winner_same_losers_check(tender),
    ]
    return ScoreResult(
        score=sum(result.score for result in results),
        reasons=[reason for result in results for reason in result.reasons],
    )


@transaction.atomic
def analyze_tender(tender: Tender) -> TenderRiskAnalysis:
    tender = (
        Tender.objects.select_related('winner_company')
        .prefetch_related('participants', 'bids__company')
        .get(pk=tender.pk)
    )

    analysis, _ = TenderRiskAnalysis.objects.get_or_create(tender=tender)
    analysis.reasons.all().delete()

    price_result = calculate_price_score(tender)
    company_result = calculate_company_history_score(tender)
    consecutive_result = calculate_consecutive_wins_score(tender)
    participants_result = calculate_participants_score(tender)
    fake_competition_result = calculate_fake_competition_score(tender)

    analysis.price_score = price_result.score
    analysis.company_history_score = company_result.score
    analysis.consecutive_wins_score = consecutive_result.score
    analysis.participants_score = participants_result.score
    analysis.fake_competition_score = fake_competition_result.score
    analysis.ai_summary = ''
    analysis.save()

    all_reasons = (
        price_result.reasons
        + company_result.reasons
        + consecutive_result.reasons
        + participants_result.reasons
        + fake_competition_result.reasons
    )
    RiskReason.objects.bulk_create(
        [
            RiskReason(
                analysis=analysis,
                title=reason.title,
                description=reason.description,
                score=reason.score,
            )
            for reason in all_reasons
        ]
    )
    analysis = TenderRiskAnalysis.objects.prefetch_related('reasons').get(pk=analysis.pk)
    analysis.ai_summary = generate_risk_summary(tender=tender, analysis=analysis)
    if analysis.ai_summary:
        analysis.save(update_fields=['ai_summary', 'analyzed_at'])
    return TenderRiskAnalysis.objects.prefetch_related('reasons').get(pk=analysis.pk)


def get_risk_stats():
    distribution = {
        item['risk_level']: item['count']
        for item in TenderRiskAnalysis.objects.values('risk_level').annotate(count=Count('id'))
    }
    organization_scores = []
    org_map: dict[str, dict] = {}
    for analysis in TenderRiskAnalysis.objects.select_related('tender'):
        org = analysis.tender.organization
        if org not in org_map:
            org_map[org] = {'organization': org, 'tender_count': 0, 'total_score': 0}
        org_map[org]['tender_count'] += 1
        org_map[org]['total_score'] += analysis.total_score
    for value in org_map.values():
        avg_score = value['total_score'] / value['tender_count']
        organization_scores.append(
            {
                'organization': value['organization'],
                'tender_count': value['tender_count'],
                'average_score': round(avg_score, 2),
            }
        )
    organization_scores.sort(key=lambda item: item['average_score'], reverse=True)
    total = Tender.objects.count()
    return {
        'total': total,
        'high': distribution.get('high', 0),
        'medium': distribution.get('medium', 0),
        'low': distribution.get('low', 0),
        'distribution': {
            'HIGH': distribution.get('high', 0),
            'MEDIUM': distribution.get('medium', 0),
            'LOW': distribution.get('low', 0),
        },
        'top_risky_organizations': organization_scores[:5],
        'total_analyzed_tenders': TenderRiskAnalysis.objects.count(),
    }
