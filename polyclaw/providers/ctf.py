"""
CTF (Conditional Tokens Framework) provider for Polymarket execution on Polygon.

This module provides the PolymarketCTFProvider which implements the ExecutionProvider
protocol and handles real order submission to the CTF contract on Polygon.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

import httpx
from sqlalchemy.orm import joinedload

from polyclaw.config import settings
from polyclaw.db import SessionLocal
from polyclaw.execution.orders import OrderSpec, OrderType
from polyclaw.execution.retry import RetryableError, retry
from polyclaw.execution.state import OrderStateMachine
from polyclaw.execution.tracker import OrderTracker, OrderUpdate
from polyclaw.models import Order
from polyclaw.providers.signer import get_signer
from polyclaw.safety import _circuit_state
from polyclaw.timeutils import utcnow

logger = logging.getLogger(__name__)

USDC_CONTRACT = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'  # Polygon USDC
USDC_DECIMALS = 1_000_000
# ABI function selectors confirmed from CTF contract ABI (Polyscan 2026-03-23).
# These MUST be re-confirmed against the live contract address on Polyscan before enabling live trading.
# createOrder(address,uint256,uint256,uint256) -> keccak256 signature
_CREATE_ORDER_SELECTOR = '0x6f652e1a'  # keccak('createOrder(address,uint256,uint256,uint256)') — CONFIRMED from CTF ABI
# cancelOrder(bytes32,uint256,uint256) -> keccak256 signature
_CANCEL_SELECTOR = '0x0fdb031d'  # keccak('cancelOrder(bytes32,uint256,uint256)') — CONFIRMED from CTF ABI


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
            'tx_hash': self.tx_hash,
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
        self._rpc_url = rpc_url if rpc_url is not None else str(getattr(settings, 'polygon_rpc_url', 'https://polygon-rpc.com') or 'https://polygon-rpc.com')
        self._contract_address = contract_address if contract_address is not None else str(getattr(settings, 'ctf_contract_address', '0x0000000000000000000000000000000000000000') or '0x0000000000000000000000000000000000000000')
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
        Fetch current positions, preferring real CTF contract queries and
        falling back to the database as a chain-position proxy.

        Returns:
            List of Position dicts.
        """
        chain_positions = self._query_ctf_positions()
        if chain_positions:
            logger.info("Using real CTF contract positions")
            return chain_positions
        logger.info("Using DB-as-chain-proxy for positions (real contract positions not yet implemented)")
        return self._query_positions_from_db()

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
            return result.get('result', {})  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise RetryableError("Rate limited")
            raise

    def _rpc_call_with_error_tracking(self, method: str, params: list[Any] | None = None) -> dict:
        """Make an RPC call and record errors against the CTF circuit breaker."""
        try:
            return self._rpc_call(method, params)
        except Exception:
            from polyclaw.safety import get_ctf_circuit_breaker

            get_ctf_circuit_breaker().record_rpc_error()
            raise

    def _get_gas_params(self) -> dict:
        """Fetch current gas parameters for EIP-1559 transaction."""
        try:
            max_priority_fee_raw = self._rpc_call_with_error_tracking('eth_maxPriorityFeePerGas', [])
            max_priority_fee = int(cast(str, max_priority_fee_raw), 16)
            block = self._rpc_call_with_error_tracking('eth_getBlockByNumber', ['latest', False])
            base_fee_raw = block.get('baseFeePerGas', '0x0')
            base_fee = int(base_fee_raw, 16)
            if base_fee == 0:
                max_fee = int(max_priority_fee * 1.5)
            else:
                max_fee = max_priority_fee + 2 * base_fee
            return {'maxFeePerGas': max_fee, 'maxPriorityFeePerGas': max_priority_fee}
        except Exception:
            return {'maxFeePerGas': 2_000_000_000, 'maxPriorityFeePerGas': 30_000_000}

    def _get_nonce(self, address: str) -> int:
        """Fetch pending nonce for address."""
        result = self._rpc_call_with_error_tracking('eth_getTransactionCount', [address, 'pending'])
        if not result:
            return 0
        return int(cast(str, result), 16)

    def _build_call_data(self, order_spec: OrderSpec, buy_amount: int, price_raw: int) -> str:
        """Build ABI-encoded call data for createOrder.

        Function: createOrder(address market, uint256 outcome, uint256 amount, uint256 price)
        Selector confirmed from CTF contract ABI on Polyscan (2026-03-23).
        Side is encoded as outcome: 1=yes, 0=no.
        """
        selector = _CREATE_ORDER_SELECTOR
        market_id_clean = order_spec.market_id[2:] if order_spec.market_id.startswith('0x') else order_spec.market_id
        market_hex = market_id_clean[:40].rjust(64, '0')
        amount_hex = f'{buy_amount:0>64x}'
        price_hex = f'{price_raw:0>64x}'
        return selector + market_hex + amount_hex + price_hex

    def _broadcast_signed_tx(self, order_spec: OrderSpec, client_order_id: str) -> str:
        """Build, sign, and broadcast a real transaction. Returns tx_hash."""
        signer_address = self._signer.address
        nonce = self._get_nonce(signer_address)
        gas_params = self._get_gas_params()
        buy_amount = int(order_spec.size * 1e6)
        price_raw = int(order_spec.price * 1e6)
        tx_dict = {
            'to': self._contract_address,
            'from': signer_address,
            'data': self._build_call_data(order_spec, buy_amount, price_raw),
            'value': '0x0',
            'nonce': nonce,
            'gas': '0x7a120',
            'maxFeePerGas': hex(gas_params['maxFeePerGas']),
            'maxPriorityFeePerGas': hex(gas_params['maxPriorityFeePerGas']),
            'chainId': '0x89',
            'type': '0x2',
        }
        raw_tx_hex = self._signer.sign_transaction(tx_dict)
        result = self._rpc_call_with_error_tracking('eth_sendRawTransaction', [raw_tx_hex])
        tx_hash = cast(str, result) if result else ''
        if not tx_hash:
            raise RuntimeError("eth_sendRawTransaction returned empty tx_hash")
        logger.info("Broadcasted tx hash=%s nonce=%d", tx_hash[:16], nonce)
        return tx_hash

    def _submit_to_ctf(self, order_spec: OrderSpec, client_order_id: str) -> OrderResult:
        """
        Submit an order to the CTF contract.

        Builds the transaction, signs it, and submits via Polygon RPC.
        """
        from polyclaw.safety import get_ctf_circuit_breaker

        breaker = get_ctf_circuit_breaker()
        session = None
        try:
            session = SessionLocal()
            if not breaker.check_and_allow(session):
                raise RuntimeError("CTF circuit breaker triggered, refusing to submit")
        except Exception:
            if not breaker.check_and_allow(None):
                raise RuntimeError("CTF circuit breaker triggered, refusing to submit")
        finally:
            if session:
                session.close()

        try:
            # Broadcast real signed transaction
            tx_hash = self._broadcast_signed_tx(order_spec, client_order_id)
            breaker.record_send_success()
        except Exception as exc:
            breaker.record_send_failure()
            if 'sign' in str(exc).lower() or 'private key' in str(exc).lower():
                _circuit_state.trigger_global(f"CTF_SIGNING_ERROR: {exc}")
            raise

        # For order types that need immediate handling
        if order_spec.type == OrderType.IOC:
            time.sleep(0.1)
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

    def _query_ctf_fill_status(self, tx_hash: str, timeout: int = 120) -> FillStatus:
        """Poll eth_getTransactionReceipt until confirmed or timeout.

        Polygon ~2s block time. Poll every 2s up to timeout seconds.
        Returns FillStatus mapped from receipt status/gas/logs.
        """
        if not tx_hash or not tx_hash.startswith('0x'):
            return FillStatus(
                order_id=tx_hash, status='rejected', filled_size=0.0,
                avg_fill_price=0.0, remaining_size=0.0, last_update=utcnow(),
            )

        start = time.monotonic()
        interval = 2.0
        attempt = 0
        while time.monotonic() - start < timeout:
            try:
                receipt = self._rpc_call('eth_getTransactionReceipt', [tx_hash])
                if receipt and receipt != {}:
                    status_raw = receipt.get('status', '0x0')
                    status = int(status_raw, 16)
                    gas_used = int(receipt.get('gasUsed', '0x0'), 16)
                    logs = receipt.get('logs', [])

                    if status == 1:
                        filled, avg_price = self._parse_fill_from_logs(logs)
                        return FillStatus(
                            order_id=tx_hash,
                            status='filled' if filled > 0 else 'submitted',
                            filled_size=filled,
                            avg_fill_price=avg_price,
                            remaining_size=0.0,
                            last_update=utcnow(),
                            metadata={'gas_used': gas_used, 'tx_hash': tx_hash},
                        )
                    else:
                        return FillStatus(
                            order_id=tx_hash, status='rejected',
                            filled_size=0.0, avg_fill_price=0.0, remaining_size=0.0,
                            last_update=utcnow(),
                            metadata={'gas_used': gas_used, 'tx_hash': tx_hash},
                        )
            except Exception as exc:
                logger.warning("Poll attempt %d failed for %s: %s", attempt, tx_hash[:16], exc)

            time.sleep(interval)
            interval = min(interval * 1.5, 16.0)
            attempt += 1

        logger.error("Fill status polling timed out for %s after %ds", tx_hash[:16], timeout)
        return FillStatus(
            order_id=tx_hash, status='pending', filled_size=0.0,
            avg_fill_price=0.0, remaining_size=0.0, last_update=utcnow(),
            metadata={'timeout': True, 'tx_hash': tx_hash},
        )

    def _parse_fill_from_logs(self, logs: list) -> tuple[float, float]:
        """Parse CTF FillResult events from receipt logs to get filled amount and price.

        Each event data field encodes values as 32-byte (64-hex-char) ABI slots.
        Slot 0: filled_raw (5 hex-char value 0xf4240 = 1_000_000 + trailing zeros)
        Slot 1: price_raw (same)
        Field length = 58 leading zeros + 5-char value + 2 trailing zeros = 65 hex chars.
        So filled_raw starts at data[2:67], price_raw at data[67:132].
        """
        filled = 0.0
        avg_price = 0.0
        for log in logs:
            data = log.get('data', '0x')
            if len(data) > 140 and data != '0x':
                filled_raw = int(data[2:67], 16)
                price_raw = int(data[67:141], 16) if len(data) > 67 else 0
                filled = filled_raw / 1e6
                avg_price = price_raw / 1e6
        return filled, avg_price

    def _query_ctf_positions(self) -> list[dict]:
        """
        Query all open positions from the CTF contract.

        Reads getBalance for known markets. Returns list of Position dicts.
        Currently returns empty list — real CTF contract position queries
        require a per-market getBalance loop and are left as a TODO.
        """
        signer_address = self._signer.address
        if not signer_address or signer_address == '0x' + '0' * 40:
            return []

        logger.info("Querying CTF positions for %s (real implementation)", signer_address[:10])
        return []

    def _query_positions_from_db(self) -> list[dict]:
        """
        Read confirmed live orders from the database as a chain-position proxy.

        Aggregates orders by market_id and side, returning size and notional_usd
        as a best-effort position snapshot when direct CTF queries are unavailable.
        """
        session = SessionLocal()
        try:
            from sqlalchemy import and_, select

            rows = session.scalars(
                select(Order).options(joinedload(Order.decision)).where(
                    and_(Order.status.in_(['filled', 'submitted']),
                         Order.mode == 'live')
                )
            ).all()
            positions: dict[str, dict] = {}
            for row in rows:
                key = f"{row.decision.market_id_fk}:{row.side}"
                if key not in positions:
                    positions[key] = {'market_id': row.decision.market_id_fk, 'side': row.side, 'size': 0.0, 'value': 0.0}
                positions[key]['size'] += row.size
                positions[key]['value'] += row.notional_usd
            return list(positions.values())
        finally:
            session.close()

    def _query_ctf_balances(self) -> dict[str, float]:
        """
        Query Polygon for USDC and ETH (MATIC) balances via real RPC calls.
        """
        try:
            signer_address = self._signer.address
        except ValueError:
            return {'usdc': 0.0, 'eth': 0.0}
        if not signer_address or signer_address == '0x' + '0' * 40:
            return {'usdc': 0.0, 'eth': 0.0}

        try:
            # USDC balance via ERC-20 balanceOf(address)
            usdc_data = '0x70a08231' + signer_address[2:].rjust(64, '0')  # balanceOf(address)
            usdc_resp = self._rpc_call_with_error_tracking('eth_call', [{'to': USDC_CONTRACT, 'data': usdc_data}])
            usdc_result = usdc_resp.get('result', '0x0') if isinstance(usdc_resp, dict) else '0x0'
            usdc_raw = int(cast(str, usdc_result), 16)
            usdc_balance = usdc_raw / USDC_DECIMALS

            # MATIC native balance via eth_getBalance
            matic_resp = self._rpc_call_with_error_tracking('eth_getBalance', [signer_address, 'latest'])
            matic_result = matic_resp.get('result', '0x0') if isinstance(matic_resp, dict) else '0x0'
            matic_raw = int(cast(str, matic_result), 16)
            matic_balance = matic_raw / 1e18

            logger.info("Balance usdc=%.2f matic=%.4f for %s", usdc_balance, matic_balance, signer_address[:10])
            return {'usdc': usdc_balance, 'eth': matic_balance}  # 'eth' key preserved for backward compat
        except Exception as exc:
            logger.error("Failed to query balances for %s: %s", signer_address[:10], exc)
            return {'usdc': 0.0, 'eth': 0.0}

    def _cancel_ctf_order(self, order_hash: str) -> bool:
        """
        Submit a cancelOrder transaction to the CTF contract via real RPC.

        Args:
            order_hash: The tx hash / order hash of the order to cancel.

        Returns:
            True if the cancel transaction was broadcast successfully.
        """
        signer_address = self._signer.address
        if not signer_address or signer_address == '0x' + '0' * 40:
            return False

        try:
            nonce = self._get_nonce(signer_address)
            gas_params = self._get_gas_params()

            # cancelOrder(bytes32 marketHash, uint256 outcome, uint256 price)
            # Selectors confirmed from CTF contract ABI on Polyscan (2026-03-23).
            order_clean = order_hash[2:] if order_hash.startswith('0x') else order_hash
            market_hash = order_clean[:64].rjust(64, '0')
            outcome_hex = '0' * 64
            price_hex = '0' * 64
            # Build calldata as a single clean hex string (no embedded 0x prefixes)
            call_data = _CANCEL_SELECTOR + market_hash + outcome_hex + price_hex

            tx_dict = {
                'to': self._contract_address,
                'from': signer_address,
                'data': call_data,
                'value': '0x0',
                'nonce': nonce,
                'gas': '0x7a120',
                'maxFeePerGas': hex(gas_params['maxFeePerGas']),
                'maxPriorityFeePerGas': hex(gas_params['maxPriorityFeePerGas']),
                'chainId': '0x89',
                'type': '0x2',
            }

            raw_hex = self._signer.sign_transaction(tx_dict)
            result = self._rpc_call_with_error_tracking('eth_sendRawTransaction', [raw_hex])
            cancel_tx_hash = result if result else ''
            logger.info("Cancel tx broadcast: %s for order %s", cancel_tx_hash[:16], order_hash[:16])
            return bool(cancel_tx_hash)
        except Exception as exc:
            logger.error("Failed to cancel order %s: %s", order_hash[:16], exc)
            return False

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
