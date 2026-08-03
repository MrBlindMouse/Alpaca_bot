# backtest/ — agent guide

## Role

Historical replay of `rebalance_tick` on cached Alpaca bars (`python -m backtest fetch|run|status`).

## File map

| File | Role |
|------|------|
| `engine.py` | Step loop + decisions file |
| `broker.py` | `SimBroker` fills |
| `cache.py` | SQLite bars (keyed by timeframe) |
| `fetch.py` | Download bars into cache |
| `compare.py` / `benchmarks.py` | Multi-strategy comparison |
| `service.py` | CLI/TUI orchestration |
| `clock.py` | RTH weekend+hours filter (no holidays) |
| `logging_setup.py` | Isolate `backtest.log` from TUI |

## Invariants

- Bars and `fetch_log` are segregated by **timeframe**; never mix 1Min/5Min in one query.
- Missing bars: carry forward last price — never mark holdings at $0.
- Shared strategy only via `rebalance_tick`; no parallel hysteresis implementation.
- Multi-margin runs write per-margin trades/equity/decisions artifacts.

## Prefer / avoid

- Prefer wipe/re-fetch after schema changes over migration frameworks.
- Avoid new ports/hexagonal layers; `broker.Broker` at repo root is enough.

## See also

- [../AGENTS.md](../AGENTS.md)
- [../tui/AGENTS.md](../tui/AGENTS.md)
