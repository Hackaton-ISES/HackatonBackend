from django.db import transaction

from tenders.models import Tender, TenderBid
from tenders.services.award_risk import ensure_application_can_be_awarded
from tenders.services.risk_scoring import analyze_companies


@transaction.atomic
def finalize_tender_winner(*, tender: Tender, application: TenderBid) -> Tender:
    if application.tender_id != tender.id:
        raise ValueError('Application does not belong to this tender.')
    if tender.winner_company_id:
        raise ValueError('Tender winner has already been finalized.')
    ensure_application_can_be_awarded(application)

    tender.bids.update(is_winner=False)
    application.is_winner = True
    application.save(update_fields=['is_winner'])

    tender.winner_company = application.company
    tender.final_price = application.bid_price
    tender.status = Tender.Status.COMPLETED
    tender.save(update_fields=['winner_company', 'final_price', 'status', 'updated_at'])

    analyze_companies(tender.participants.values_list('id', flat=True))
    return tender
