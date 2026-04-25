from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from tenders.models import Company, Tender


class RiskLevel(StrEnum):
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'


@dataclass(frozen=True)
class RiskAnalysisResult:
    risk_score: int
    risk_level: str
    reasons: list[str]


def _company_win_rate(company: Company) -> Decimal:
    if company.total_participations == 0:
        return Decimal('0')
    return Decimal(company.total_wins) / Decimal(company.total_participations)


def analyze_tender_risk(tender: Tender) -> RiskAnalysisResult:
    score = 0
    reasons: list[str] = []

    if tender.final_price > tender.average_market_price * Decimal('1.3'):
        score += 30
        reasons.append('Price anomaly: final price exceeds market average by more than 30%.')

    if tender.participants_count == 1:
        score += 20
        reasons.append('Single bidder: only one company participated in the tender.')

    winner = tender.winner_company
    if winner and _company_win_rate(winner) > Decimal('0.70'):
        score += 20
        reasons.append(
            f'Winner pattern: {winner.name} has a win rate above 70% across tenders.'
        )

    repeated_losers = []
    for participant in tender.participants.all():
        if participant.total_participations > 5 and participant.total_wins == 0:
            repeated_losers.append(participant.name)

    if repeated_losers:
        score += 10
        reasons.append(
            'Repeated loser pattern: '
            + ', '.join(repeated_losers)
            + ' participated more than 5 times without any wins.'
        )

    if tender.budget and (tender.final_price / tender.budget) > Decimal('0.95'):
        score += 15
        reasons.append('Too perfect pricing: final price is above 95% of the budget.')

    if (tender.deadline - tender.created_at).days < 3:
        score += 15
        reasons.append('Deadline manipulation risk: submission window is shorter than 3 days.')

    score = min(score, 100)

    if score >= 70:
        level = RiskLevel.HIGH
    elif score >= 35:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW

    if not reasons:
        reasons.append('No predefined corruption risk rules were triggered.')

    return RiskAnalysisResult(
        risk_score=score,
        risk_level=level,
        reasons=reasons,
    )
