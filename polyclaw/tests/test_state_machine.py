"""Tests for the order state machine."""

import pytest

from polyclaw.execution.state import (
    VALID_TRANSITIONS,
    OrderState,
    OrderStateMachine,
    StateTransition,
)


class MockOrder:
    """A mock Order object for testing state transitions."""

    def __init__(self, status: str = 'submitted'):
        self.status = status
        self.status_history: list = []
        self.updated_at = None


class MockSession:
    """A minimal mock session for testing."""

    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True

    def flush(self):
        pass


class TestOrderStateMachine:
    """Tests for OrderStateMachine."""

    def test_valid_transitions_from_created(self):
        """Orders in 'created' state can transition to submitted or canceled."""
        sm = OrderStateMachine()
        assert sm.can_transition(OrderState.CREATED, OrderState.SUBMITTED)
        assert sm.can_transition(OrderState.CREATED, OrderState.CANCELED)
        assert not sm.can_transition(OrderState.CREATED, OrderState.FILLED)
        assert not sm.can_transition(OrderState.CREATED, OrderState.PARTIAL_FILL)

    def test_valid_transitions_from_submitted(self):
        """Orders in 'submitted' state have multiple valid transitions."""
        sm = OrderStateMachine()
        assert sm.can_transition(OrderState.SUBMITTED, OrderState.ACKNOWLEDGED)
        assert sm.can_transition(OrderState.SUBMITTED, OrderState.PARTIAL_FILL)
        assert sm.can_transition(OrderState.SUBMITTED, OrderState.FILLED)
        assert sm.can_transition(OrderState.SUBMITTED, OrderState.CANCELING)
        assert sm.can_transition(OrderState.SUBMITTED, OrderState.REJECTED)
        assert sm.can_transition(OrderState.SUBMITTED, OrderState.FAILED)
        assert not sm.can_transition(OrderState.SUBMITTED, OrderState.CANCELED)

    def test_terminal_states_have_no_transitions(self):
        """Terminal states (filled, canceled, rejected, failed) cannot transition."""
        sm = OrderStateMachine()
        terminal_states = [
            OrderState.FILLED,
            OrderState.CANCELED,
            OrderState.REJECTED,
            OrderState.FAILED,
        ]
        all_states = list(OrderState)

        for terminal in terminal_states:
            for target in all_states:
                assert not sm.can_transition(terminal, target), \
                    f"{terminal.value} should not transition to {target.value}"

    def test_get_allowed_transitions(self):
        """get_allowed_transitions returns the correct set."""
        sm = OrderStateMachine()
        allowed = sm.get_allowed_transitions(OrderState.SUBMITTED)
        assert OrderState.ACKNOWLEDGED in allowed
        assert OrderState.FILLED in allowed
        assert OrderState.CANCELING in allowed
        assert OrderState.CANCELED not in allowed

    def test_transition_updates_status(self):
        """A successful transition updates the order status."""
        sm = OrderStateMachine()
        order = MockOrder(status='submitted')
        session = MockSession()

        transition = sm.transition(order, OrderState.ACKNOWLEDGED, session, {'tx_hash': '0x123'})

        assert order.status == 'acknowledged'
        assert session.committed
        assert transition.from_state == 'submitted'
        assert transition.to_state == 'acknowledged'
        assert 'tx_hash' in transition.metadata

    def test_transition_appends_to_history(self):
        """Transitions are appended to status_history."""
        sm = OrderStateMachine()
        order = MockOrder(status='submitted')
        order.status_history = []
        session = MockSession()

        sm.transition(order, OrderState.ACKNOWLEDGED, session, {'note': 'test'})
        sm.transition(order, OrderState.FILLED, session, {})

        assert len(order.status_history) == 2
        assert order.status_history[0]['from'] == 'submitted'
        assert order.status_history[0]['to'] == 'acknowledged'
        assert order.status_history[1]['from'] == 'acknowledged'
        assert order.status_history[1]['to'] == 'filled'

    def test_invalid_transition_raises(self):
        """An invalid transition raises ValueError."""
        sm = OrderStateMachine()
        order = MockOrder(status='filled')
        session = MockSession()

        with pytest.raises(ValueError, match='Invalid order state transition'):
            sm.transition(order, OrderState.SUBMITTED, session)

    def test_canceling_can_transition_to_canceled(self):
        """CANCELING -> CANCELED is a valid transition."""
        sm = OrderStateMachine()
        assert sm.can_transition(OrderState.CANCELING, OrderState.CANCELED)
        assert sm.can_transition(OrderState.CANCELING, OrderState.FAILED)

    def test_partial_fill_can_stay_in_partial_fill(self):
        """Orders can remain in partial_fill as more fills come in."""
        sm = OrderStateMachine()
        assert sm.can_transition(OrderState.PARTIAL_FILL, OrderState.PARTIAL_FILL)

    def test_partial_fill_can_transition_to_filled(self):
        """A partial fill can complete to filled."""
        sm = OrderStateMachine()
        assert sm.can_transition(OrderState.PARTIAL_FILL, OrderState.FILLED)
        assert sm.can_transition(OrderState.PARTIAL_FILL, OrderState.CANCELING)

    def test_transition_creates_state_transition_record(self):
        """transition() returns a StateTransition record."""
        sm = OrderStateMachine()
        order = MockOrder(status='submitted')
        session = MockSession()

        transition = sm.transition(order, OrderState.FILLED, session)

        assert isinstance(transition, StateTransition)
        assert transition.from_state == 'submitted'
        assert transition.to_state == 'filled'
        assert transition.timestamp is not None
        assert transition.metadata == {}


class TestOrderStateEnum:
    """Tests for the OrderState enum."""

    def test_all_states_have_string_values(self):
        """All order states should have string values matching their name."""
        for state in OrderState:
            assert state.value == state.name.lower()

    def test_state_values_match_model_constants(self):
        """State values should match Order model constants."""
        from polyclaw.models import Order

        assert OrderState.CREATED.value == Order.STATUS_CREATED
        assert OrderState.SUBMITTED.value == Order.STATUS_SUBMITTED
        assert OrderState.ACKNOWLEDGED.value == Order.STATUS_ACKNOWLEDGED
        assert OrderState.PARTIAL_FILL.value == Order.STATUS_PARTIAL_FILL
        assert OrderState.FILLED.value == Order.STATUS_FILLED
        assert OrderState.CANCELING.value == Order.STATUS_CANCELING
        assert OrderState.CANCELED.value == Order.STATUS_CANCELED
        assert OrderState.REJECTED.value == Order.STATUS_REJECTED
        assert OrderState.FAILED.value == Order.STATUS_FAILED

    def test_valid_transitions_map_matches_enum(self):
        """VALID_TRANSITIONS should use OrderState enum keys."""
        for from_state, to_states in VALID_TRANSITIONS.items():
            assert isinstance(from_state, OrderState)
            for to_state in to_states:
                assert isinstance(to_state, OrderState)
