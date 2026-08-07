# tui/ — agent guide

## Role

Textual terminal UI (`python -m tui`) for bot control, analytics, logs, and backtest tab.

## File map

| File | Role |
|------|------|
| `app.py` | Main screen / tabs (large; extend carefully) |
| `widgets.py` | Shared Static/table formatters |
| `ui_refresh.py` | Conditional Static text updates (SSH flicker) |
| `table_refresh.py` | DataTable signature + scroll preserve |
| `table_sort.py` | Column sort keys |
| `log_tail.py` | Byte-offset log tail |

## Invariants

- Logging must not write to the console while the TUI runs (`setup_logging(..., console=False)`).
- Prefer tab-scoped refresh; avoid full-screen redraws.
- Force balance (`f` / Positions button) calls `BotRunner.force_balance` (RTH only, no hysteresis); do not invoke `rebalance_tick` from the UI thread.
- Write-off (`w` / Positions button) calls `BotRunner.write_off` (quarantine orphan; no order); do not place sells from the UI thread.

## Prefer / avoid

- Prefer updating helpers in `table_*` / `ui_refresh` over bloating `app.py`.
- Avoid new UI frameworks or card-heavy layouts.

## See also

- [../AGENTS.md](../AGENTS.md)
- [../backtest/AGENTS.md](../backtest/AGENTS.md)
