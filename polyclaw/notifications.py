from sqlalchemy.orm import Session

from polyclaw.safety import log_event


class NotificationService:
    @staticmethod
    def notify(session: Session, channel: str, message: str) -> None:
        log_event(session, f'notify:{channel}', message, 'queued')
