"""Live trading prerequisite validation — all checks must pass before live mode is allowed."""
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class PrereqCheck:
    name: str
    passed: bool
    detail: str = ''


class LiveTradingPrerequisites:
    """Validates all prerequisites for live trading mode.

    Call check_all() before enabling live_trading_enabled.
    Raises PrerequisiteError if any check fails.
    """

    def __init__(self, ctf_provider, signer, settings):
        self.ctf_provider = ctf_provider
        self.signer = signer
        self.settings = settings

    def check_all(self) -> list[PrereqCheck]:
        checks: list[PrereqCheck] = []

        # 1. Private key
        try:
            addr = self.signer.address
            checks.append(PrereqCheck(name='private_key', passed=True, detail=f'address={addr[:10]}...'))
        except Exception as exc:
            checks.append(PrereqCheck(name='private_key', passed=False, detail=str(exc)))

        # 2. Contract address not zero
        addr = getattr(self.settings, 'ctf_contract_address', '')
        passed = bool(addr and addr != '0x' + '0' * 40)
        checks.append(PrereqCheck(
            name='contract_address',
            passed=passed,
            detail=addr if passed else 'not configured or zero'
        ))

        # 3. RPC URL reachable — do a real JSON-RPC eth_blockNumber call
        try:
            rpc_url = getattr(self.settings, 'polygon_rpc_url', '') or 'https://polygon-rpc.com'
            payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
            resp = httpx.post(rpc_url, json=payload, timeout=5, headers={"Content-Type": "application/json"})
            rpc_ok = resp.status_code == 200 and "result" in resp.json()
            checks.append(PrereqCheck(
                name='rpc_reachable',
                passed=rpc_ok,
                detail=f'HTTP {resp.status_code}'
            ))
        except Exception as exc:
            checks.append(PrereqCheck(name='rpc_reachable', passed=False, detail=str(exc)))

        # 4. Selectors confirmed (not placeholders)
        from polyclaw.providers import ctf as ctf_module
        create_sel = getattr(ctf_module, '_CREATE_ORDER_SELECTOR', '0x00000000')
        cancel_sel = getattr(ctf_module, '_CANCEL_SELECTOR', '0x00000000')
        placeholders = create_sel == '0x00000000' or cancel_sel == '0x00000000' or \
                       create_sel == '0xabc12345' or cancel_sel == '0xabc12345'
        checks.append(PrereqCheck(
            name='selectors_confirmed',
            passed=not placeholders,
            detail=f'create={create_sel}, cancel={cancel_sel}'
        ))

        # 5. Balances reachable
        try:
            bals = self.ctf_provider.get_balances()
            checks.append(PrereqCheck(
                name='balances_queryable',
                passed=True,
                detail=f'usdc={bals.get("usdc", "N/A")}'
            ))
        except Exception as exc:
            checks.append(PrereqCheck(name='balances_queryable', passed=False, detail=str(exc)))

        return checks

    def raise_if_any_failed(self) -> None:
        """Raise PrerequisiteError listing all failed checks."""
        checks = self.check_all()
        failed = [c for c in checks if not c.passed]
        if failed:
            names = ', '.join(c.name for c in failed)
            details = '; '.join(f'{c.name}={c.detail}' for c in failed)
            raise PrerequisiteError(f"Live trading prerequisites failed: [{names}]. Details: {details}")


class PrerequisiteError(ValueError):
    """Raised when live trading prerequisites are not met."""
    pass
