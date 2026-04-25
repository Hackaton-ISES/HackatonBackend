from dataclasses import dataclass
from enum import StrEnum

from tenders.models import Tender
from tenders.services.risk_scoring import analyze_tender


class RiskLevel(StrEnum):
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'


@dataclass(frozen=True)
class RiskAnalysisResult:
    risk_score: int
    risk_level: str
    reasons: list[str]


def analyze_tender_risk(tender: Tender) -> RiskAnalysisResult:
    analysis = analyze_tender(tender)
    return RiskAnalysisResult(
        risk_score=analysis.total_score,
        risk_level=analysis.risk_level.upper(),
        reasons=[reason.description for reason in analysis.reasons.all()],
    )
