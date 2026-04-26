from dataclasses import dataclass
from enum import StrEnum

from tenders.models import Company
from tenders.services.risk_scoring import analyze_company


class RiskLevel(StrEnum):
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'


@dataclass(frozen=True)
class RiskAnalysisResult:
    suspicion_score: int
    suspicion_level: str
    reasons: list[str]


def analyze_company_risk(company: Company) -> RiskAnalysisResult:
    analysis = analyze_company(company)
    return RiskAnalysisResult(
        suspicion_score=analysis.total_score,
        suspicion_level=analysis.suspicion_level.upper(),
        reasons=[reason.description for reason in analysis.reasons.all()],
    )
