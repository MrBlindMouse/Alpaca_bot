# tests/ — agent guide

## Role

Pytest suite for money-path, scheduler, backtest, and TUI helper behavior. Prefer one focused assert per bug/regression (see `test_audit_fixes.py`).

## File map

| Pattern | Focus |
|---------|--------|
| `test_rebalance_*.py` | Strategy / hysteresis / limits |
| `test_orders.py`, `test_partial_limit_fill.py` | Order poll, fills, dry-run |
| `test_backtest_*.py` | Cache, engine, compare, fetch |
| `test_scheduler_*.py`, `test_runner.py` | Tick loop, circuit, day_end timing |
| `test_tui_*.py`, `test_table_*.py`, `test_ui_refresh.py` | TUI helpers only (not full app) |

## Invariants

- Do not hit live Alpaca; mock HTTP/sessions.
- Money-path regressions belong in a small dedicated test, not a giant fixture suite.

## Prefer / avoid

- Prefer assert-on-behavior with `MagicMock`.
- Avoid new test frameworks or fixture factories.

## See also

- [../AGENTS.md](../AGENTS.md)
