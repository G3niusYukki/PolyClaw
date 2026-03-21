from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.models import ProposalRecord
from polyclaw.notifications import NotificationService
from polyclaw.proposals import ProposalPreview
from polyclaw.safety import log_event
from polyclaw.timeutils import utcnow


class ProposalWorkflowService:
    def persist_previews(self, session: Session, previews: list[ProposalPreview]) -> int:
        created = 0
        for item in previews:
            record = session.scalar(select(ProposalRecord).where(ProposalRecord.market_id == item.market.market_id, ProposalRecord.status.in_(['new', 'reviewed', 'approved'])))
            if record:
                continue
            record = ProposalRecord(
                market_id=item.market.market_id,
                title=item.market.title,
                suggested_side=item.suggested_side,
                confidence=item.confidence,
                edge_bps=item.edge_bps,
                suggested_stake_usd=item.suggested_stake_usd,
                explanation=item.explanation,
                ranking_reasons='|'.join(item.ranking_reasons),
                evidence_summaries='|'.join(e.summary for e in item.evidences),
                risk_flags='|'.join(item.risk_flags),
                status='new',
            )
            session.add(record)
            created += 1
        session.flush()
        return created

    def set_status(self, session: Session, proposal_id: int, status: str) -> ProposalRecord | None:
        record = session.get(ProposalRecord, proposal_id)
        if not record:
            return None
        record.status = status
        record.updated_at = utcnow()
        log_event(session, 'proposal_status', f'id={proposal_id}|status={status}', 'ok')
        if status == 'approved':
            NotificationService.notify(session, 'internal', f'Proposal approved: {record.title}')
        session.commit()
        session.refresh(record)
        return record
