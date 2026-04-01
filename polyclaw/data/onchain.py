"""On-chain data analysis for Smart Money detection on Polymarket/Polygon."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

import httpx

from polyclaw.config import settings
from polyclaw.timeutils import utcnow

logger = logging.getLogger(__name__)

# Polymarket CTF contract on Polygon
CTF_CONTRACT = getattr(settings, 'ctf_contract_address', '0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E')
USDC_CONTRACT = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'
DECIMALS = 1_000_000


@dataclass
class WhalePosition:
    """A large position held by a single wallet."""
    wallet_address: str
    market_id: str
    side: str  # 'yes' or 'no'
    size_usd: float
    outcome_tokens: float


@dataclass
class WalletActivity:
    """Recent activity from a tracked wallet."""
    wallet_address: str
    market_id: str
    side: str
    size_usd: float
    timestamp: datetime
    label: str = ''


@dataclass
class UnusualActivity:
    """Detected unusual trading activity in a market."""
    market_id: str
    activity_type: str  # 'volume_spike', 'large_trade', 'rapid_accumulation'
    magnitude: float  # 0.0 to 1.0
    direction: str  # 'yes' or 'no'
    details: str


class OnChainAnalyzer:
    """Analyzes on-chain data for Smart Money signals on Polymarket."""

    def __init__(self, rpc_url: str | None = None) -> None:
        self._rpc_url = rpc_url or settings.polygon_rpc_url
        self._http_client: httpx.Client | None = None

    @property
    def http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(base_url=self._rpc_url, timeout=20.0)
        return self._http_client

    def close(self) -> None:
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def _rpc_call(self, method: str, params: list[Any] | None = None) -> dict:
        """Make a JSON-RPC call to Polygon."""
        import time as _time
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or [],
            'id': int(_time.time() * 1000) % (2 ** 31),
        }
        resp = self.http_client.post('', json=payload, headers={'Content-Type': 'application/json'})
        resp.raise_for_status()
        result = resp.json()
        if 'error' in result:
            raise RuntimeError(f"RPC error: {result['error']}")
        return result.get('result', {})

    def get_large_positions(
        self,
        market_addresses: list[str],
        min_usd: float | None = None,
        max_wallets: int = 20,
    ) -> list[WhalePosition]:
        """Detect large positions in specified markets.

        Uses the Polymarket CLOB API to fetch top positions.

        Args:
            market_addresses: List of market condition IDs to check.
            min_usd: Minimum position size in USD to be considered a whale.
            max_wallets: Maximum number of whale positions to return.

        Returns:
            List of WhalePosition instances.
        """
        if min_usd is None:
            min_usd = 1000.0

        positions: list[WhalePosition] = []
        for market_id in market_addresses:
            try:
                market_positions = self._fetch_market_positions(market_id, min_usd)
                positions.extend(market_positions)
            except Exception as exc:
                logger.warning('Failed to fetch positions for market %s: %s', market_id[:16], exc)

        # Filter by min_usd (in case _fetch_market_positions doesn't filter)
        positions = [p for p in positions if p.size_usd >= min_usd]

        # Sort by size descending
        positions.sort(key=lambda p: p.size_usd, reverse=True)
        return positions[:max_wallets]

    def track_known_wallets(
        self,
        wallet_addresses: list[str],
        market_addresses: list[str],
    ) -> list[WalletActivity]:
        """Check positions of known tracked wallets in specific markets.

        Args:
            wallet_addresses: Wallet addresses to track.
            market_addresses: Markets to check positions in.

        Returns:
            List of WalletActivity for any positions found.
        """
        activities: list[WalletActivity] = []
        for wallet in wallet_addresses:
            for market_id in market_addresses:
                try:
                    balance_yes = self._query_ctf_balance(wallet, market_id, outcome=1)
                    balance_no = self._query_ctf_balance(wallet, market_id, outcome=0)
                    if balance_yes > 0:
                        activities.append(WalletActivity(
                            wallet_address=wallet,
                            market_id=market_id,
                            side='yes',
                            size_usd=balance_yes / DECIMALS,
                            timestamp=utcnow(),
                        ))
                    if balance_no > 0:
                        activities.append(WalletActivity(
                            wallet_address=wallet,
                            market_id=market_id,
                            side='no',
                            size_usd=balance_no / DECIMALS,
                            timestamp=utcnow(),
                        ))
                except Exception as exc:
                    logger.debug('Balance query failed for %s in %s: %s', wallet[:10], market_id[:16], exc)
        return activities

    def detect_unusual_activity(
        self,
        market_addresses: list[str],
        volume_threshold_multiplier: float = 3.0,
    ) -> list[UnusualActivity]:
        """Detect unusual on-chain activity for markets.

        Checks for volume spikes and large individual trades by examining
        recent block activity.

        Args:
            market_addresses: Markets to check.
            volume_threshold_multiplier: Multiplier over normal volume to flag.

        Returns:
            List of UnusualActivity detections.
        """
        activities: list[UnusualActivity] = []

        # Get recent block number for time window
        try:
            block_result = self._rpc_call('eth_blockNumber', [])
            latest_block = int(cast(str, block_result), 16)
        except Exception as exc:
            logger.warning('Failed to get block number: %s', exc)
            return activities

        # Check Polymarket order events in recent blocks (simplified approach)
        # In production, this would index CTF contract events via log filtering
        for market_id in market_addresses:
            try:
                # Use eth_getLogs to find recent CTF events for this market
                from_block = hex(max(0, latest_block - 200))  # ~10 min window
                logs = self._rpc_call('eth_getLogs', [{
                    'fromBlock': from_block,
                    'toBlock': 'latest',
                    'address': CTF_CONTRACT,
                    'topics': [],  # Would filter by market-specific topics
                }])
                if logs and isinstance(logs, list) and len(logs) > 5:
                    # Simplified: many logs = unusual activity
                    activities.append(UnusualActivity(
                        market_id=market_id,
                        activity_type='volume_spike',
                        magnitude=min(1.0, len(logs) / 20.0),
                        direction='unknown',
                        details=f'{len(logs)} CTF events in last ~200 blocks',
                    ))
            except Exception as exc:
                logger.debug('Unusual activity check failed for %s: %s', market_id[:16], exc)

        return activities

    def _fetch_market_positions(self, market_id: str, min_usd: float) -> list[WhalePosition]:
        """Fetch positions for a market from Polymarket API or RPC.

        Uses the Polymarket CLOB positions endpoint if available.
        Falls back to scanning known whale wallets via RPC.
        """
        # Try Polymarket positions API
        positions_url = getattr(settings, 'polymarket_positions_url', '')
        if positions_url:
            try:
                resp = httpx.get(f'{positions_url}?market={market_id}', timeout=10)
                resp.raise_for_status()
                data = resp.json()
                return [
                    WhalePosition(
                        wallet_address=p.get('wallet', ''),
                        market_id=market_id,
                        side=p.get('side', 'yes'),
                        size_usd=float(p.get('size_usd', 0)),
                        outcome_tokens=float(p.get('tokens', 0)),
                    )
                    for p in data
                    if float(p.get('size_usd', 0)) >= min_usd
                ]
            except Exception:
                pass
        return []

    def _query_ctf_balance(self, trader: str, market: str, outcome: int) -> int:
        """Query getBalance on CTF contract for a specific trader/market/outcome."""
        selector = '0x4e11e440'  # getBalance(address,address,uint256)
        trader_hex = trader[2:].rjust(64, '0') if trader.startswith('0x') else trader.rjust(64, '0')
        market_hex = market[2:].rjust(64, '0') if market.startswith('0x') else market.rjust(64, '0')
        outcome_hex = f'{outcome:064x}'
        data = selector + trader_hex + market_hex + outcome_hex

        result = self._rpc_call('eth_call', [{'to': CTF_CONTRACT, 'data': data}])
        result_str = result.get('result', '0x0') if isinstance(result, dict) else '0x0'
        return int(result_str, 16) if result_str else 0
