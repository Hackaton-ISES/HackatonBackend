from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from tenders.models import Company, CompanySuspicionAnalysis, Tender, TenderAuditApproval, TenderBid
from tenders.services.risk_scoring import analyze_company


HUNDRED = Decimal('100')


@dataclass(frozen=True)
class AwardRiskReason:
    rule: str
    title: str
    description: str
    severity: str
    points: int


def _baseline_for_tender(tender: Tender) -> tuple[str, Decimal]:
    if tender.average_market_price and tender.average_market_price > 0:
        return ('average_market_price', tender.average_market_price)
    return ('budget', tender.budget)


def _price_delta_percent(proposed_price: Decimal, baseline: Decimal) -> int:
    if baseline <= 0:
        return 0
    delta = ((proposed_price - baseline) / baseline) * HUNDRED
    return int(delta.quantize(Decimal('1')))


def _participant_reasons(*, company: Company, analysis, bid: TenderBid, baseline: Decimal) -> tuple[int, str, list[AwardRiskReason]]:
    points = 0
    reasons: list[AwardRiskReason] = []
    delta_percent = _price_delta_percent(bid.bid_price, baseline)

    if analysis.suspicion_level == 'high':
        points += 35
        reasons.append(
            AwardRiskReason(
                rule='COMPANY_SUSPICION',
                title='High company suspicion',
                description=f'{company.name} has a high suspicion profile with score {analysis.total_score}.',
                severity='critical',
                points=35,
            )
        )
    elif analysis.suspicion_level == 'medium':
        points += 20
        reasons.append(
            AwardRiskReason(
                rule='COMPANY_SUSPICION',
                title='Medium company suspicion',
                description=f'{company.name} has a medium suspicion profile with score {analysis.total_score}.',
                severity='warning',
                points=20,
            )
        )

    if company.failed_projects >= 3:
        points += 25
        reasons.append(
            AwardRiskReason(
                rule='FAILED_EXECUTION',
                title='Delivery risk',
                description=f'Company has {company.failed_projects} previous failed projects.',
                severity='critical',
                points=25,
            )
        )
    elif company.failed_projects >= 1:
        points += 15
        reasons.append(
            AwardRiskReason(
                rule='FAILED_EXECUTION',
                title='Previous failed projects',
                description=f'Company has {company.failed_projects} previous failed project(s).',
                severity='warning',
                points=15,
            )
        )

    if company.total_wins >= 7:
        points += 15
        reasons.append(
            AwardRiskReason(
                rule='CONSECUTIVE_WINS',
                title='Repeated winner pattern',
                description=f'Company has {company.total_wins} previous wins.',
                severity='warning',
                points=15,
            )
        )
    elif company.total_wins >= 3:
        points += 10
        reasons.append(
            AwardRiskReason(
                rule='CONSECUTIVE_WINS',
                title='Repeated win history',
                description=f'Company has {company.total_wins} previous wins.',
                severity='warning',
                points=10,
            )
        )

    if delta_percent >= 25:
        points += 35
        reasons.append(
            AwardRiskReason(
                rule='PRICE_ANOMALY',
                title='Price anomaly',
                description=f'Bid is {delta_percent}% above the baseline.',
                severity='critical',
                points=35,
            )
        )
    elif delta_percent >= 10:
        points += 20
        reasons.append(
            AwardRiskReason(
                rule='PRICE_ANOMALY',
                title='Above-baseline bid',
                description=f'Bid is {delta_percent}% above the baseline.',
                severity='warning',
                points=20,
            )
        )
    elif delta_percent <= -30:
        points += 20
        reasons.append(
            AwardRiskReason(
                rule='UNREALISTIC_DISCOUNT',
                title='Unrealistic discount',
                description=f'Bid is {abs(delta_percent)}% below the baseline.',
                severity='warning',
                points=20,
            )
        )

    if analysis.suspicion_level == CompanySuspicionAnalysis.SuspicionLevel.HIGH:
        recommendation = 'audit_required'
        label = 'Do not award without audit'
    elif points >= 30:
        recommendation = 'review'
        label = 'Review'
    else:
        recommendation = 'safe'
        label = 'Safe'

    return points, recommendation, reasons, label, delta_percent


def get_tender_award_risk(tender: Tender) -> dict:
    source, baseline_amount = _baseline_for_tender(tender)
    participants = []

    for bid in tender.bids.select_related('company').order_by('bid_price', 'id'):
        company = bid.company
        analysis = analyze_company(company)
        _, recommendation, reasons, label, delta_percent = _participant_reasons(
            company=company,
            analysis=analysis,
            bid=bid,
            baseline=baseline_amount,
        )
        participants.append(
            {
                'applicationId': bid.external_id,
                'companyId': company.external_id,
                'companyName': company.name,
                'proposedPrice': bid.bid_price,
                'priceDeltaPercent': delta_percent,
                'companySuspicionScore': analysis.total_score,
                'companySuspicionLevel': analysis.suspicion_level.upper(),
                'failedProjects': company.failed_projects,
                'totalWins': company.total_wins,
                'recommendation': recommendation,
                'recommendationLabel': label,
                'reasons': [
                    {
                        'rule': reason.rule,
                        'title': reason.title,
                        'description': reason.description,
                        'severity': reason.severity,
                        'points': reason.points,
                    }
                    for reason in reasons
                ],
            }
        )

    return {
        'tenderId': tender.external_id,
        'baseline': {
            'source': source,
            'amount': baseline_amount,
        },
        'participants': participants,
        'generatedAt': timezone.now(),
    }


def ensure_application_can_be_awarded(application: TenderBid) -> None:
    analysis = analyze_company(application.company)
    if analysis.suspicion_level != CompanySuspicionAnalysis.SuspicionLevel.HIGH:
        return

    has_approval = TenderAuditApproval.objects.filter(
        tender=application.tender,
        application=application,
    ).exists()
    if not has_approval:
        raise ValueError('Audit approval is required for HIGH risk companies.')
