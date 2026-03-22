"""
CTF (Conditional Tokens Framework) provider for Polymarket execution on Polygon.

This module provides the PolymarketCTFProvider which implements the ExecutionProvider
protocol and handles real order submission to the CTF contract on Polygon.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from polyclaw.config import settings
from polyclaw.db import SessionLocal
from polyclaw.execution.orders import OrderSpec, OrderType
from polyclaw.execution.retry import retry, RetryableError
from polyclaw.execution.state import OrderState, OrderStateMachine
from polyclaw.execution.tracker import OrderTracker, OrderUpdate
from polyclaw.models import Order
from polyclaw.providers.base import ExecutionProvider
from polyclaw.providers.signer import get_signer
from polyclaw.timeutils import utcnow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Transfer Objects
# ---------------------------------------------------------------------------


@dataclass
class OrderResult:
    """Result of an order submission."""
    client_order_id: str
    venue_order_id: str
    status: str
    side: str
    price: float
    size: float
    notional_usd: float
    mode: str = 'live'
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    tx_hash: str = ''
    error: str = ''
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'client_order_id': self.client_order_id,
            'venue_order_id': self.venue_order_id,
            'status': self.status,
            'side': self.side,
            'price': self.price,
            'size': self.size,
            'notional_usd': self.notional_usd,
            'mode': self.mode,
            'filled_size': self.filled_size,
            'avg_fill_price': self.avg_fill_price,
            'venue_order_id': self.tx_hash,
        }


@dataclass
class FillStatus:
    """Status of an order fill from the CTF contract."""
    order_id: str
    status: str  # pending, filled, partial_fill, canceled, rejected
    filled_size: float
    avg_fill_price: float
    remaining_size: float
    last_update: datetime
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# CTF Provider
# ---------------------------------------------------------------------------


class PolymarketCTFProvider:
    """
    ExecutionProvider implementation for real Polymarket CTF trading on Polygon.

    This provider handles:
    - Order submission with wallet signing
    - Fill status checking via Polygon RPC
    - Position and balance queries
    - Idempotent order submission via client_order_id
    - All order types (LIMIT, IOC, POST_ONLY, MARKET)

    Uses mock CTF contract calls for now; actual ABI integration is a placeholder.
    """

    def __init__(
        self,
        rpc_url: str | None = None,
        contract_address: str | None = None,
    ):
        """
        Initialize the CTF provider.

        Args:
            rpc_url: Polygon RPC URL. Defaults to POLYGON_RPC_URL from settings.
            contract_address: CTF contract address. Defaults to CTF_CONTRACT_ADDRESS.
        """
        self._rpc_url = rpc_url or getattr(settings, 'polygon_rpc_url', 'https://polygon-rpc.com')
        self._contract_address = contract_address or getattr(settings, 'ctf_contract_address', '0x0000000000000000000000000000000000000000')
        self._http_client: httpx.Client | None = None
        self._signer = get_signer()
        self._state_machine = OrderStateMachine()
        self._tracker = OrderTracker(fulfill=self)

    @property
    def http_client(self) -> httpx.Client:
        """Get or create the HTTP client for RPC calls."""
        if self._http_client is None:
            self._http_client = httpx.Client(
                base_url=self._rpc_url,
                timeout=30.0,
            )
        return self._http_client

    def close(self):
        """Close the HTTP client."""
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    # -------------------------------------------------------------------------
    # ExecutionProvider implementation (backward compatible)
    # -------------------------------------------------------------------------

    def submit_order(
        self,
        market: Any,
        side: str,
        stake_usd: float,
        price: float,
    ) -> dict:
        """
        Submit an order (backward-compatible interface).

        This matches the original ExecutionProvider signature and is used
        by ExecutionService.process_ready_decisions().
        """
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side=side,
            price=price,
            size=stake_usd / max(price, 0.01),
            market_id=getattr(market, 'market_id', 'unknown'),
            outcome=side,
            client_order_id=f'ctf-{uuid.uuid4().hex[:16]}',
        )
        result = self.submit_order_obj(order_spec, market)
        return result.to_dict()

    def submit_order_obj(
        self,
        order_spec: OrderSpec,
        market: Any | None = None,
    ) -> OrderResult:
        """
        Submit an order with full OrderSpec support.

        Implements idempotent order submission: if a client_order_id already
        exists in the database, returns the cached result instead of resubmitting.

        Args:
            order_spec: The order specification.
            market: Optional market snapshot for additional context.

        Returns:
            OrderResult with the submission result.
        """
        client_order_id = order_spec.client_order_id or f'ctf-{uuid.uuid4().hex[:16]}'

        # Idempotency check: look for existing order with this client_order_id
        existing = self._get_existing_order(client_order_id)
        if existing:
            logger.info("Idempotent return for client_order_id=%s", client_order_id)
            return OrderResult(
                client_order_id=existing.client_order_id,
                venue_order_id=existing.venue_order_id,
                status=existing.status,
                side=existing.side,
                price=existing.price,
                size=existing.size,
                notional_usd=existing.notional_usd,
                mode='live',
            )

        # Submit to CTF
        result = self._submit_to_ctf(order_spec, client_order_id)

        # Persist the order to DB
        self._persist_order_result(result, order_spec, market)

        return result

    def check_fill(self, order: Order | object) -> OrderUpdate:
        """
        Check the fill status of an order by querying the CTF contract.

        This implements the OrderFulfiller protocol.

        Args:
            order: The SQLAlchemy Order model instance.

        Returns:
            OrderUpdate with the current fill status.
        """
        venue_order_id = getattr(order, 'venue_order_id', '')
        client_order_id = getattr(order, 'client_order_id', '')

        if not venue_order_id:
            return OrderUpdate(
                order_id=getattr(order, 'id', 0),
                client_order_id=client_order_id,
                status=getattr(order, 'status', 'submitted'),
                updated_at=utcnow(),
            )

        try:
            fill_status = self._query_ctf_fill_status(venue_order_id)
            return OrderUpdate(
                order_id=getattr(order, 'id', 0),
                client_order_id=client_order_id,
                status=fill_status.status,
                filled_size=fill_status.filled_size,
                avg_fill_price=fill_status.avg_fill_price,
                updated_at=fill_status.last_update,
                metadata=fill_status.metadata,
            )
        except Exception as exc:
            logger.warning("Failed to query CTF fill status for %s: %s", venue_order_id, exc)
            return OrderUpdate(
                order_id=getattr(order, 'id', 0),
                client_order_id=client_order_id,
                status=getattr(order, 'status', 'submitted'),
                updated_at=utcnow(),
            )

    def get_positions(self) -> list[dict]:
        """
        Fetch current positions from the CTF contract.

        Returns:
            List of Position dicts from the CTF.
        """
        return self._query_ctf_positions()

    def get_balances(self) -> dict[str, float]:
        """
        Fetch USDC and ETH balances from Polygon.

        Returns:
            Dict with 'usdc' and 'eth' balance values.
        """
        return self._query_ctf_balances()

    def cancel_order(self, order: Order | object) -> bool:
        """
        Cancel an order on the CTF contract.

        Args:
            order: The SQLAlchemy Order model instance.

        Returns:
            True if cancellation was successful.
        """
        venue_order_id = getattr(order, 'venue_order_id', '')
        if not venue_order_id:
            return False

        try:
            return self._cancel_ctf_order(venue_order_id)
        except Exception as exc:
            logger.error("Failed to cancel CTF order %s: %s", venue_order_id, exc)
            return False

    # -------------------------------------------------------------------------
    # Internal CTF methods (mock implementations)
    # -------------------------------------------------------------------------

    @retry(max_attempts=3, base_delay=1.0, exponential_base=2.0)
    def _rpc_call(self, method: str, params: list[Any] | None = None) -> dict:
        """
        Make a JSON-RPC call to the Polygon RPC endpoint.

        Retries on connection errors and timeouts.
        """
        params = params or []
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': int(time.time() * 1000) % (2 ** 31),
        }

        try:
            response = self.http_client.post(
                '',
                json=payload,
                headers={'Content-Type': 'application/json'},
            )
            response.raise_for_status()
            result = response.json()
            if 'error' in result:
                raise RetryableError(f"RPC error: {result['error']}")
            return result.get('result', {})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise RetryableError("Rate limited")
            raise

    def _submit_to_ctf(self, order_spec: OrderSpec, client_order_id: str) -> OrderResult:
        """
        Submit an order to the CTF contract.

        Builds the transaction, signs it, and submits via Polygon RPC.
        Mock implementation for now.
        """
        signer_address = self._signer.address

        # Build the CTF transaction payload
        tx_data = order_spec.to_ctf_payload(self._contract_address, signer_address)

        # Sign the transaction
        signature = self._signer.sign_transaction(tx_data)

        # Submit via RPC (mock: simulate successful submission)
        tx_hash = self._simulate_ctf_submission(tx_data, signature)

        # For order types that need immediate handling
        if order_spec.type == OrderType.IOC:
            # IOC orders: submit and immediately check fill
            time.sleep(0.1)  # Brief wait for block confirmation
            fill_status = self._query_ctf_fill_status(tx_hash)
            if fill_status.filled_size == 0:
                self._cancel_ctf_order(tx_hash)
                return OrderResult(
                    client_order_id=client_order_id,
                    venue_order_id=tx_hash,
                    status='canceled',
                    side=order_spec.side,
                    price=order_spec.price,
                    size=order_spec.size,
                    notional_usd=order_spec.notional_usd,
                    mode='live',
                    error='IOC order not filled, canceled',
                )

        return OrderResult(
            client_order_id=client_order_id,
            venue_order_id=tx_hash,
            status='submitted',
            side=order_spec.side,
            price=order_spec.price,
            size=order_spec.size,
            notional_usd=order_spec.notional_usd,
            mode='live',
            tx_hash=tx_hash,
        )

    def _simulate_ctf_submission(self, tx_data: dict, signature: str) -> str:
        """
        Simulate a CTF order submission.

        Mock implementation that returns a deterministic "transaction hash"
        based on the transaction data.
        """
        tx_bytes = json.dumps(tx_data, sort_keys=True).encode() + signature.encode()
        tx_hash = '0x' + hashlib.sha256(tx_bytes).hexdigest()
        return tx_hash

    def _query_ctf_fill_status(self, tx_hash: str) -> FillStatus:
        """
        Query the CTF contract for order fill status.

        Mock implementation that simulates fill status based on tx_hash.
        """
        hash_byte = int(tx_hash[-8:], 16) if tx_hash.startswith('0x') else 0
        fill_pct = (hash_byte % 100) / 100.0
        if fill_pct < 0.70:
            status = 'filled'
            filled_size = 1.0
            avg_price = 0.55
        elif fill_pct < 0.90:
            status = 'partial_fill'
            filled_size = 0.5
            avg_price = 0.55
        else:
            status = 'pending'
            filled_size = 0.0
            avg_price = 0.0

        return FillStatus(
            order_id=tx_hash,
            status=status,
            filled_size=filled_size,
            avg_fill_price=avg_price,
            remaining_size=max(0, 1.0 - filled_size),
            last_update=utcnow(),
        )

    def _query_ctf_positions(self) -> list[dict]:
        """
        Query the CTF contract for current positions.

        Mock implementation.
        """
        signer_address = self._signer.address
        if not signer_address or signer_address == '0x' + '0' * 40:
            return []
        return []

    def _query_ctf_balances(self) -> dict[str, float]:
        """
        Query Polygon for USDC and ETH balances.

        Mock implementation.
        """
        signer_address = self._signer.address
        if not signer_address or signer_address == '0x' + '0' * 40:
            return {'usdc': 0.0, 'eth': 0.0}
        return {
            'usdc': 1000.0,
            'eth': 0.5,
        }

    def _cancel_ctf_order(self, tx_hash: str) -> bool:
        """
        Cancel an order on the CTF contract.

        Mock implementation.
        """
        logger.info("Mock: canceling CTF order %s", tx_hash)
        return True

    # -------------------------------------------------------------------------
    # Database helpers
    # -------------------------------------------------------------------------

    def _get_existing_order(self, client_order_id: str) -> Order | None:
        """Check if an order with the given client_order_id already exists."""
        session = SessionLocal()
        try:
            from sqlalchemy import select
            return session.scalar(
                select(Order).where(Order.client_order_id == client_order_id)
            )
        finally:
            session.close()

    def _persist_order_result(
        self,
        result: OrderResult,
        order_spec: OrderSpec,
        market: Any | None,
    ) -> Order:
        """Persist an OrderResult to the database."""
        session = SessionLocal()
        try:
            from sqlalchemy import select
            from polyclaw.models import Decision, Market

            # Find the decision for this market if market is provided
            decision_id_fk: int | None = None
            if market is not None:
                market_id = getattr(market, 'market_id', None)
                if market_id:
                    market_record = session.scalar(
                        select(Market).where(Market.market_id == market_id)
                    )
                    if market_record:
                        decision = session.scalar(
                            select(Decision)
                            .where(Decision.market_id_fk == market_record.id)
                            .where(Decision.status == 'proposed')
                            .order_by(Decision.created_at.desc())
                        )
                        if decision:
                            decision_id_fk = decision.id

            # Create the order record
            order = Order(
                decision_id_fk=decision_id_fk,
                client_order_id=result.client_order_id,
                venue_order_id=result.venue_order_id,
                status=result.status,
                side=result.side,
                price=result.price,
                size=result.size,
                notional_usd=result.notional_usd,
                mode='live',
                retry_count=0,
            )
            session.add(order)
            session.flush()

            # Initialize status_history
            if hasattr(order, 'status_history'):
                order.status_history = [{
                    'from': '',
                    'to': 'submitted',
                    'timestamp': utcnow().isoformat(),
                }]

            session.commit()
            session.refresh(order)
            return order
        except Exception as exc:
            session.rollback()
            logger.error("Failed to persist order result: %s", exc)
            raise
        finally:
            session.close()
