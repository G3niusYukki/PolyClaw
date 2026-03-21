from typing import Protocol

from polyclaw.domain import EvidenceItem, MarketSnapshot


class MarketProvider(Protocol):
    def list_markets(self, limit: int) -> list[MarketSnapshot]: ...


class EvidenceProvider(Protocol):
    def gather(self, market: MarketSnapshot) -> list[EvidenceItem]: ...


class ExecutionProvider(Protocol):
    def submit_order(self, market: MarketSnapshot, side: str, stake_usd: float, price: float) -> dict: ...
