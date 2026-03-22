from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.execution.orders import OrderSpec, OrderType
from polyclaw.execution.price_bands import PriceBandValidator
from polyclaw.models import Decision, Market
from polyclaw.providers.paper_execution import PaperExecutionProvider
from polyclaw.repositories import record_order_and_position
from polyclaw.safety import daily_executed_notional, kill_switch_state, log_event
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from polyclaw.providers.ctf import PolymarketCTFProvider


class ExecutionService:
    def __init__(self):
        self.executor = PaperExecutionProvider()
        self._ctf_executor: PolymarketCTFProvider | None = None
        self._price_validator = PriceBandValidator()

    @property
    def ctf_executor(self) -> 'PolymarketCTFProvider':
        """Lazy-load the CTF executor to avoid circular imports."""
        if self._ctf_executor is None:
            from polyclaw.providers.ctf import PolymarketCTFProvider
            self._ctf_executor = PolymarketCTFProvider()
        return self._ctf_executor

    def process_ready_decisions(self, session: Session) -> tuple[int, int]:
        if kill_switch_state(session)['enabled']:
            log_event(session, 'execution_skip', 'kill switch enabled', 'blocked')
            session.commit()
            return 0, 0

        # When shadow mode is enabled, skip real execution
        if not settings.shadow_mode_enabled:
            return self._process_real_decisions(session)

        # Shadow mode: process signals without real submission
        return self._process_shadow_decisions(session)

    def _process_real_decisions(self, session: Session) -> tuple[int, int]:
        """Process decisions with real order submission (paper or live)."""
        stmt = select(Decision, Market).join(Market, Decision.market_id_fk == Market.id).where(Decision.status == 'proposed')
        rows = session.execute(stmt).all()
        considered = len(rows)
        submitted = 0
        failures = 0
        daily_notional = daily_executed_notional(session)

        for decision, market in rows:
            if decision.requires_approval and settings.require_approval:
                continue
            if daily_notional + decision.stake_usd > settings.max_daily_loss_usd:
                log_event(session, 'execution_skip', f'daily cap exceeded for decision={decision.id}', 'blocked')
                continue

            # Determine execution price
            price = market.outcome_yes_price if decision.side == 'yes' else market.outcome_no_price
            market_id = getattr(market, 'market_id', 'unknown')

            # Validate price band (fat finger protection)
            order_spec = OrderSpec(
                type=OrderType.LIMIT,
                side=decision.side,
                price=price,
                size=decision.stake_usd / max(price, 0.01),
                market_id=market_id,
                outcome=decision.side,
            )
            is_valid, reason = self._price_validator.validate(order_spec, price)
            if not is_valid:
                log_event(session, 'price_band_rejected', f'decision={decision.id}|{reason}', 'rejected')
                continue

            try:
                # Use CTF provider for live mode, paper for paper mode
                if settings.execution_mode == 'live':
                    payload = self.ctf_executor.submit_order(market, decision.side, decision.stake_usd, price)
                else:
                    payload = self.executor.submit_order(market, decision.side, decision.stake_usd, price)
                record_order_and_position(session, market, decision, payload)
                daily_notional += decision.stake_usd
                submitted += 1
                log_event(session, 'order_submitted', f'decision={decision.id}|market={market.market_id}|side={decision.side}', 'ok')
            except Exception as exc:
                failures += 1
                log_event(session, 'order_failed', f'decision={decision.id}|error={exc}', 'error')
                if failures >= settings.max_consecutive_failures:
                    log_event(session, 'kill_switch', 'consecutive execution failures', 'enabled')
                    break
        session.commit()
        return considered, submitted

    def _process_shadow_decisions(self, session: Session) -> tuple[int, int]:
        """Process decisions in shadow mode (simulated execution without real orders)."""
        from polyclaw.shadow.mode import ShadowModeEngine

        stmt = (
            select(Decision, Market)
            .join(Market, Decision.market_id_fk == Market.id)
            .where(Decision.status == 'proposed')
        )
        rows = session.execute(stmt).all()
        considered = len(rows)
        shadow_positions_created = 0

        for decision, market in rows:
            if decision.requires_approval and settings.require_approval:
                continue

            engine = ShadowModeEngine()
            shadow_fill_price = engine.calculate_shadow_fill_price(market, decision.side)

            # Calculate quantity
            price_for_qty = market.outcome_yes_price if decision.side == 'yes' else market.outcome_no_price
            quantity = round(decision.stake_usd / max(price_for_qty, 0.01), 4)

            now = utcnow()

            # Create shadow position in DB
            from polyclaw.models import Position
            shadow_pos = Position(
                event_key=market.event_key,
                market_id=market.market_id,
                side=decision.side,
                notional_usd=decision.stake_usd,
                avg_price=shadow_fill_price,
                quantity=quantity,
                opened_at=now,
                is_open=True,
                is_shadow=True,
                strategy_id=getattr(decision, 'strategy_id', '') if hasattr(decision, 'strategy_id') else '',
            )
            session.add(shadow_pos)

            # Create shadow result for accuracy tracking
            from polyclaw.models import ShadowResult
            shadow_result = ShadowResult(
                market_id=market.market_id,
                strategy_id=getattr(decision, 'strategy_id', '') if hasattr(decision, 'strategy_id') else '',
                predicted_side=decision.side,
                predicted_prob=decision.confidence,
                shadow_fill_price=shadow_fill_price,
                actual_outcome='',
                pnl=0.0,
                accuracy=False,
                resolved_at=None,
                created_at=now,
            )
            session.add(shadow_result)

            decision.status = 'executed'
            shadow_positions_created += 1

            log_event(
                session,
                'shadow_position_created',
                f'decision={decision.id}|market={market.market_id}|side={decision.side}|fill_price={shadow_fill_price}',
                'ok',
            )

        session.commit()
        return considered, shadow_positions_created

    def approve(self, session: Session, decision_id: int) -> Decision | None:
        decision = session.get(Decision, decision_id)
        if not decision:
            return None
        decision.requires_approval = False
        decision.approved_at = utcnow()
        session.commit()
        session.refresh(decision)
        return decision
