# PolyClaw Safety Checklist

## Before enabling anything beyond paper mode

- [ ] No private keys or seed phrases stored in code or repo
- [ ] Child wallet / limited-risk wallet only
- [ ] `live_trading_enabled=true` set explicitly by operator
- [ ] Approval gate reviewed
- [ ] Kill switch tested
- [ ] Daily loss limit tested
- [ ] Consecutive failure halt tested
- [ ] Stale data rejection tested
- [ ] Low-liquidity rejection tested
- [ ] Audit logs visible and queryable
- [ ] Rollback path documented

## v1 release policy

- Default to paper mode
- Default to manual approval
- Do not enable unattended live trading in v1
- Only allow high-liquidity markets
- Start with small notional and staged rollout
