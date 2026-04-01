"""Order state machine for managing order lifecycle transitions."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from polyclaw.timeutils import utcnow

logger = logging.getLogger(__name__)


class OrderState(str, Enum):
    """Valid states in the order lifecycle."""
    CREATED = 'created'
    SUBMITTED = 'submitted'
    ACKNOWLEDGED = 'acknowledged'
    PARTIAL_FILL = 'partial_fill'
    FILLED = 'filled'
    CANCELING = 'canceling'
    CANCELED = 'canceled'
    REJECTED = 'rejected'
    FAILED = 'failed'


# Valid state transitions: from_state -> set of allowed to_states
VALID_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.CREATED: {
        OrderState.SUBMITTED,
        OrderState.CANCELED,
    },
    OrderState.SUBMITTED: {
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIAL_FILL,
        OrderState.FILLED,
        OrderState.CANCELING,
        OrderState.REJECTED,
        OrderState.FAILED,
    },
    OrderState.ACKNOWLEDGED: {
        OrderState.PARTIAL_FILL,
        OrderState.FILLED,
        OrderState.CANCELING,
        OrderState.FAILED,
    },
    OrderState.PARTIAL_FILL: {
        OrderState.PARTIAL_FILL,  # can stay in partial fill (more fills)
        OrderState.FILLED,
        OrderState.CANCELING,
        OrderState.FAILED,
    },
    OrderState.FILLED: set(),  # terminal state
    OrderState.CANCELING: {
        OrderState.CANCELED,
        OrderState.FAILED,
    },
    OrderState.CANCELED: set(),  # terminal state
    OrderState.REJECTED: set(),  # terminal state
    OrderState.FAILED: set(),  # terminal state
}


@dataclass
class StateTransition:
    """Records a single state transition event."""
    from_state: str
    to_state: str
    timestamp: datetime
    metadata: dict = field(default_factory=dict)


class OrderStateMachine:
    """
    Manages order state transitions with validation, history tracking, and event emission.

    Usage:
        sm = OrderStateMachine()
        sm.transition(order, OrderState.SUBMITTED, session, {'tx_hash': '0x...'})
    """

    def transition(
        self,
        order: object,
        new_state: OrderState,
        session: Session,
        metadata: dict | None = None,
    ) -> StateTransition:
        """
        Transition an order to a new state.

        Args:
            order: The SQLAlchemy Order model instance.
            new_state: The target state.
            session: The SQLAlchemy session for committing changes.
            metadata: Optional dict of metadata to record with the transition.

        Returns:
            The StateTransition record.

        Raises:
            ValueError: If the transition is not valid from the current state.
        """
        metadata = metadata or {}
        current_state = OrderState(getattr(order, 'status', 'created'))
        target_state = new_state

        # Validate the transition
        allowed = VALID_TRANSITIONS.get(current_state, set())
        if target_state not in allowed:
            raise ValueError(
                f"Invalid order state transition: {current_state.value} -> "
                f"{target_state.value}. Allowed from {current_state.value}: "
                f"{{{', '.join(s.value for s in allowed)}}}"
            )

        # Record the transition
        transition_record = StateTransition(
            from_state=current_state.value,
            to_state=target_state.value,
            timestamp=utcnow(),
            metadata=metadata,
        )

        # Append to status_history (initialize if needed)
        history = self._get_history(order)
        history.append({
            'from': transition_record.from_state,
            'to': transition_record.to_state,
            'timestamp': transition_record.timestamp.isoformat(),
            **{k: str(v) for k, v in metadata.items()},
        })

        # Update the order
        _order: Any = order
        _order.status = target_state.value
        if hasattr(order, 'status_history'):
            order.status_history = history
        if hasattr(order, 'updated_at'):
            order.updated_at = utcnow()

        session.commit()

        # Emit notification event
        self._emit_event(order, transition_record)

        logger.info(
            "Order %s transitioned: %s -> %s",
            getattr(order, 'client_order_id', 'unknown'),
            current_state.value,
            target_state.value,
        )

        return transition_record

    def _get_history(self, order: object) -> list[dict]:
        """Get the status history list from an order, initializing if needed."""
        history = getattr(order, 'status_history', None)
        if history is None:
            return []
        if isinstance(history, str):
            # Handle JSON string if stored as string
            import json
            try:
                return json.loads(history)  # type: ignore[no-any-return]
            except Exception:
                return []
        return list(history)

    def _emit_event(self, order: object, transition: StateTransition) -> None:
        """Log the state transition event."""
        logger.info(
            "Order state change: %s -> %s for order %s",
            transition.from_state,
            transition.to_state,
            getattr(order, 'client_order_id', 'unknown'),
        )

    def can_transition(self, current_state: OrderState, target_state: OrderState) -> bool:
        """Check if a transition is valid without raising an error."""
        allowed = VALID_TRANSITIONS.get(current_state, set())
        return target_state in allowed

    def get_allowed_transitions(self, current_state: OrderState) -> set[OrderState]:
        """Return the set of states that can be transitioned to from the current state."""
        return VALID_TRANSITIONS.get(current_state, set())
