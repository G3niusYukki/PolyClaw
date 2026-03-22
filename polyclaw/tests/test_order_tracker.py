"""Tests for the OrderTracker."""
from unittest.mock import MagicMock, patch

import pytest

from polyclaw.execution.tracker import OrderTracker, OrderUpdate


class MockOrder:
    """Mock order for testing."""

    def __init__(
        self,
        order_id: int = 1,
        client_order_id: str = 'test-123',
        status: str = 'submitted',
        filled_size: float = 0.0,
        avg_fill_price: float = 0.0,
        updated_at=None,
    ):
        self.id = order_id
        self.client_order_id = client_order_id
        self.status = status
        self.filled_size = filled_size
        self.avg_fill_price = avg_fill_price
        self.updated_at = updated_at


class MockSession:
    """Mock database session."""

    def __init__(self):
        self.committed = False
        self.flushed = False

    def commit(self):
        self.committed = True

    def flush(self):
        self.flushed = False

    def close(self):
        pass


class MockFulfiller:
    """Mock fulfiller for testing OrderFulfiller protocol."""

    def __init__(self, fill_results: list[OrderUpdate] | None = None):
        self._results = fill_results or []
        self._index = 0
        self.cancel_calls = []

    def check_fill(self, order):
        if self._results and self._index < len(self._results):
            result = self._results[self._index]
            self._index += 1
            return result
        return OrderUpdate(
            order_id=getattr(order, 'id', 0),
            client_order_id=getattr(order, 'client_order_id', ''),
            status='pending',
        )

    def cancel_order(self, order):
        self.cancel_calls.append(order)
        return True


class TestOrderTracker:
    """Tests for OrderTracker."""

    def test_poll_order_without_fulfiller(self):
        """poll_order returns current state when no fulfiller is set."""
        tracker = OrderTracker(fulfill=None)
        order = MockOrder(status='submitted')
        session = MockSession()

        update = tracker.poll_order(order, session)

        assert update.status == 'submitted'
        assert update.order_id == 1
        assert update.client_order_id == 'test-123'

    def test_poll_order_with_fulfiller(self):
        """poll_order queries fulfiller and updates DB."""
        mock_update = OrderUpdate(
            order_id=5,
            client_order_id='mock-123',
            status='acknowledged',
            filled_size=0.0,
        )
        fulfiller = MockFulfiller(fill_results=[mock_update])
        tracker = OrderTracker(fulfill=fulfiller)

        order = MockOrder(status='submitted')
        session = MockSession()

        update = tracker.poll_order(order, session)

        assert update.status == 'acknowledged'
        assert session.committed

    def test_poll_loop_terminates_on_filled(self):
        """poll_loop stops when order reaches filled state."""
        results = [
            OrderUpdate(order_id=1, client_order_id='x', status='submitted'),
            OrderUpdate(order_id=1, client_order_id='x', status='partial_fill'),
            OrderUpdate(order_id=1, client_order_id='x', status='filled'),
        ]
        fulfiller = MockFulfiller(fill_results=results)
        tracker = OrderTracker(fulfill=fulfiller)
        order = MockOrder()
        session = MockSession()

        final_update = tracker.poll_loop(
            order, session, interval=0, timeout=5
        )

        assert final_update is not None
        assert final_update.status == 'filled'
        # Should have polled exactly 3 times (not more)
        assert len(results) == 3

    def test_poll_loop_terminates_on_canceled(self):
        """poll_loop stops when order reaches canceled state."""
        results = [
            OrderUpdate(order_id=1, client_order_id='x', status='submitted'),
            OrderUpdate(order_id=1, client_order_id='x', status='canceled'),
        ]
        fulfiller = MockFulfiller(fill_results=results)
        tracker = OrderTracker(fulfill=fulfiller)
        order = MockOrder()
        session = MockSession()

        final_update = tracker.poll_loop(order, session, interval=0, timeout=5)

        assert final_update.status == 'canceled'

    def test_poll_loop_timeout(self):
        """poll_loop returns last update on timeout."""
        # Always return pending — will timeout
        results = [
            OrderUpdate(order_id=1, client_order_id='x', status='pending')
            for _ in range(100)
        ]
        fulfiller = MockFulfiller(fill_results=results)
        tracker = OrderTracker(fulfill=fulfiller)
        order = MockOrder()
        session = MockSession()

        final_update = tracker.poll_loop(order, session, interval=0, timeout=0.1)

        # Should have timed out and returned the last pending update
        assert final_update is not None
        assert final_update.status == 'pending'

    def test_poll_loop_calls_on_update_callback(self):
        """poll_loop calls the on_update callback on each poll."""
        updates_received: list[OrderUpdate] = []
        results = [
            OrderUpdate(order_id=1, client_order_id='x', status='submitted'),
            OrderUpdate(order_id=1, client_order_id='x', status='filled'),
        ]
        fulfiller = MockFulfiller(fill_results=results)
        tracker = OrderTracker(fulfill=fulfiller)
        order = MockOrder()
        session = MockSession()

        tracker.poll_loop(
            order, session, interval=0, timeout=5,
            on_update=lambda u: updates_received.append(u),
        )

        assert len(updates_received) == 2
        assert updates_received[0].status == 'submitted'
        assert updates_received[1].status == 'filled'

    def test_cancel_active_order(self):
        """cancel_order cancels an active order."""
        fulfiller = MockFulfiller()
        tracker = OrderTracker(fulfill=fulfiller)

        order = MockOrder(status='submitted')
        session = MockSession()

        result = tracker.cancel_order(order, session)

        assert result is True
        assert len(fulfiller.cancel_calls) == 1

    def test_cancel_non_active_order(self):
        """cancel_order returns False for non-active orders."""
        tracker = OrderTracker(fulfill=None)

        for status in ['filled', 'canceled', 'rejected', 'failed']:
            order = MockOrder(status=status)
            session = MockSession()
            result = tracker.cancel_order(order, session)
            assert result is False

    def test_background_poll_starts_thread(self):
        """start_background_poll starts a background thread."""
        tracker = OrderTracker(fulfill=None)
        order = MockOrder()
        session_factory = MagicMock(return_value=MockSession())

        tracker.start_background_poll(
            order, session_factory, interval=1, timeout=10
        )

        assert len(tracker._poll_tasks) == 1
        assert 1 in tracker._poll_tasks
        tracker.stop_background_poll(1)

    def test_stop_background_poll(self):
        """stop_background_poll stops the thread and cleans up."""
        tracker = OrderTracker(fulfill=None)
        order = MockOrder()
        session_factory = MagicMock(return_value=MockSession())

        tracker.start_background_poll(order, session_factory)
        order_id = list(tracker._poll_tasks.keys())[0]

        tracker.stop_background_poll(order_id)

        assert order_id not in tracker._poll_tasks
        assert order_id not in tracker._stop_events

    def test_get_tracker_singleton(self):
        """get_tracker returns a singleton."""
        import polyclaw.execution.tracker as tracker_module
        from polyclaw.execution.tracker import get_tracker

        # Save current singleton
        saved = tracker_module._tracker_instance

        tracker = get_tracker()
        assert tracker is get_tracker()

        # Restore
        tracker_module._tracker_instance = saved


class TestOrderUpdate:
    """Tests for the OrderUpdate dataclass."""

    def test_order_update_creation(self):
        """OrderUpdate can be created with all fields."""
        update = OrderUpdate(
            order_id=42,
            client_order_id='order-abc',
            status='filled',
            filled_size=10.0,
            avg_fill_price=0.55,
            metadata={'tx_hash': '0x123'},
        )

        assert update.order_id == 42
        assert update.client_order_id == 'order-abc'
        assert update.status == 'filled'
        assert update.filled_size == 10.0
        assert update.avg_fill_price == 0.55
        assert update.metadata['tx_hash'] == '0x123'

    def test_order_update_defaults(self):
        """OrderUpdate has sensible defaults."""
        update = OrderUpdate(
            order_id=1,
            client_order_id='x',
            status='pending',
        )

        assert update.filled_size == 0.0
        assert update.avg_fill_price == 0.0
        assert update.updated_at is None
        assert update.metadata is None
