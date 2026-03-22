"""Order tracking and polling for CTF order status updates."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from sqlalchemy.orm import Session

from polyclaw.execution.state import OrderState
from polyclaw.timeutils import utcnow

logger = logging.getLogger(__name__)


@dataclass
class OrderUpdate:
    """Represents a snapshot of an order's current state."""
    order_id: int
    client_order_id: str
    status: str
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    updated_at: datetime | None = None
    metadata: dict | None = None


class OrderFulfiller(Protocol):
    """Protocol for order fill checking. Implemented by CTF provider."""

    def check_fill(self, order: object) -> OrderUpdate: ...
    def cancel_order(self, order: object) -> bool: ...


class OrderTracker:
    """
    Tracks order status and polls for fill updates.

    Supports both background thread polling and one-shot polling.
    Updates order status in the database on each poll.
    """

    def __init__(self, fulfill: OrderFulfiller | None = None):
        """
        Initialize the tracker.

        Args:
            fulfill: An object implementing OrderFulfiller protocol for checking fills.
                     If None, the tracker will only update local state.
        """
        self._fulfiller = fulfill
        self._poll_tasks: dict[int, threading.Thread] = {}
        self._stop_events: dict[int, threading.Event] = {}

    def poll_order(self, order: object, session: Session) -> OrderUpdate:
        """
        Check the current status of an order and update the DB.

        Args:
            order: The SQLAlchemy Order model instance.
            session: The SQLAlchemy session.

        Returns:
            An OrderUpdate with the latest status.
        """
        if self._fulfiller is None:
            # Return current state without querying CTF
            return OrderUpdate(
                order_id=order.id,
                client_order_id=order.client_order_id,
                status=order.status,
                filled_size=getattr(order, 'filled_size', 0.0),
                avg_fill_price=getattr(order, 'avg_fill_price', 0.0),
                updated_at=getattr(order, 'updated_at', None),
                metadata=None,
            )

        try:
            update = self._fulfiller.check_fill(order)

            # Update the order in the DB
            if hasattr(order, 'status'):
                order.status = update.status
            if hasattr(order, 'filled_size'):
                order.filled_size = update.filled_size
            if hasattr(order, 'avg_fill_price'):
                order.avg_fill_price = update.avg_fill_price
            if hasattr(order, 'updated_at'):
                order.updated_at = utcnow()

            session.commit()

            logger.debug(
                "Order %s poll: status=%s filled_size=%.4f",
                order.client_order_id,
                update.status,
                update.filled_size,
            )

            return update
        except Exception as exc:
            logger.warning("Failed to poll order %s: %s", getattr(order, 'client_order_id', 'unknown'), exc)
            return OrderUpdate(
                order_id=getattr(order, 'id', 0),
                client_order_id=getattr(order, 'client_order_id', ''),
                status=getattr(order, 'status', 'unknown'),
            )

    def poll_loop(
        self,
        order: object,
        session: Session,
        interval: int = 5,
        timeout: int = 60,
        on_update: Callable[[OrderUpdate], None] | None = None,
    ) -> OrderUpdate | None:
        """
        Poll an order until it is filled, canceled, or timeout is reached.

        This is a blocking call that runs in the current thread.

        Args:
            order: The SQLAlchemy Order model instance.
            session: The SQLAlchemy session.
            interval: Polling interval in seconds (default 5).
            timeout: Maximum time to poll in seconds (default 60).
            on_update: Optional callback called with each OrderUpdate.

        Returns:
            The final OrderUpdate when polling ends, or None on timeout.
        """
        terminal_states = {'filled', 'canceled', 'rejected', 'failed'}
        start_time = time.time()
        last_update: OrderUpdate | None = None

        while time.time() - start_time < timeout:
            update = self.poll_order(order, session)
            last_update = update

            if on_update:
                try:
                    on_update(update)
                except Exception as exc:
                    logger.warning("on_update callback failed: %s", exc)

            if update.status in terminal_states:
                logger.info(
                    "Order %s reached terminal state: %s",
                    update.client_order_id,
                    update.status,
                )
                return update

            time.sleep(interval)

        logger.info(
            "Order %s poll timed out after %ds (last status: %s)",
            getattr(order, 'client_order_id', 'unknown'),
            timeout,
            last_update.status if last_update else 'unknown',
        )
        return last_update

    def start_background_poll(
        self,
        order: object,
        session_factory: Callable[[], Session],
        interval: int = 5,
        timeout: int = 60,
        on_update: Callable[[OrderUpdate], None] | None = None,
    ) -> None:
        """
        Start polling an order in a background thread.

        The background thread will poll until the order reaches a terminal
        state or the timeout is reached.

        Args:
            order: The SQLAlchemy Order model instance.
            session_factory: A callable that returns a new Session instance.
            interval: Polling interval in seconds.
            timeout: Maximum polling time in seconds.
            on_update: Optional callback for each update.
        """
        order_id = getattr(order, 'id', id(order))
        if order_id in self._poll_tasks:
            logger.warning("Background poll already running for order %s", order_id)
            return

        stop_event = threading.Event()
        self._stop_events[order_id] = stop_event

        def _poll_thread():
            session = session_factory()
            try:
                terminal_states = {'filled', 'canceled', 'rejected', 'failed'}
                start_time = time.time()

                while not stop_event.is_set():
                    if time.time() - start_time >= timeout:
                        break

                    update = self.poll_order(order, session)
                    if on_update:
                        try:
                            on_update(update)
                        except Exception as exc:
                            logger.warning("on_update callback failed: %s", exc)

                    if update.status in terminal_states:
                        break

                    stop_event.wait(timeout=interval)
            except Exception as exc:
                logger.error("Background poll thread error for order %s: %s", order_id, exc)
            finally:
                session.close()
                self._poll_tasks.pop(order_id, None)
                self._stop_events.pop(order_id, None)

        thread = threading.Thread(target=_poll_thread, daemon=True)
        self._poll_tasks[order_id] = thread
        thread.start()

        logger.info(
            "Started background poll for order %s (interval=%ds, timeout=%ds)",
            getattr(order, 'client_order_id', order_id),
            interval,
            timeout,
        )

    def stop_background_poll(self, order_id: int) -> None:
        """Stop a background polling thread for a given order."""
        stop_event = self._stop_events.get(order_id)
        if stop_event:
            stop_event.set()
            thread = self._poll_tasks.get(order_id)
            if thread:
                thread.join(timeout=5.0)
                logger.info("Stopped background poll for order %s", order_id)

    def cancel_order(self, order: object, session: Session) -> bool:
        """
        Cancel an order if it is still active.

        Args:
            order: The SQLAlchemy Order model instance.
            session: The SQLAlchemy session.

        Returns:
            True if cancellation was successful, False otherwise.
        """
        active_states = {'submitted', 'acknowledged', 'partial_fill'}
        if getattr(order, 'status', '') not in active_states:
            return False

        if self._fulfiller is None:
            logger.warning("No fulfiller configured, cannot cancel order")
            return False

        try:
            result = self._fulfiller.cancel_order(order)
            if result:
                from polyclaw.execution.state import OrderStateMachine
                sm = OrderStateMachine()
                sm.transition(order, OrderState.CANCELING, session)
            return result
        except Exception as exc:
            logger.error("Failed to cancel order %s: %s", getattr(order, 'client_order_id', 'unknown'), exc)
            return False


# Module-level singleton
_tracker_instance: OrderTracker | None = None


def get_tracker() -> OrderTracker:
    """Get or create the module-level OrderTracker singleton."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = OrderTracker()
    return _tracker_instance
