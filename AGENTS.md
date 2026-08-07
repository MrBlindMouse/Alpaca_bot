# Alpaca_bot — agent guide

Personal NASDAQ-100 equal-weight rebalancer on Alpaca (paper or live).

## Layout

| Module | Role |
|--------|------|
| `bot.py` | Headless CLI entry point |
| `runner.py` | `BotRunner` — adaptive tick loop, `force_balance` (RTH one-shot), `write_off` |
| `tui/` | Textual TUI (`python -m tui`) — see [tui/AGENTS.md](tui/AGENTS.md) |
| `analytics.py` | Trade/portfolio stats from `trades.jsonl` (+ `orders.jsonl` for fill-rate) |
| `env_config.py` | `.env` margin read/write |
| `config.py` | `.env` loading and validation |
| `state.py` | `Status` and `trading_state.json` |
| `alpaca_client.py` | HTTP session, account, positions |
| `ticker_source.py` | SlickCharts scrape + Alpaca asset filter |
| `market.py` | Market clock (`ClockSnapshot`, `next_open`), extended hours, calendar |
| `rebalance.py` | `rebalance_tick` (shared strategy), `force_rebalance_symbol` (RTH one-shot), `maintain_open_limits`, slim `bot()` |
| `broker.py` | `Broker` protocol (live + sim) |
| `live_broker.py` | `LiveBroker` — Alpaca adapter for `rebalance_tick` |
| `orders.py` | `create_order`, `OrderResult`, trade logging hooks |
| `trade_log.py` | Append-only `trades.jsonl` (fills) and `orders.jsonl` (non-fills) |
| `remote.py` | Optional HMAC webhook (`post_event`; env-gated) |
| `reporting.py` | Day-end equity payload |
| `scheduler.py` | `bot_loop`, hourly balance check |
| `resilience.py` | Circuit breaker for consecutive API failures |
| `utils.py` | `trunc()` |
| `backtest/` | Historical replay — see [backtest/AGENTS.md](backtest/AGENTS.md) |
| `tests/` | pytest suite — see [tests/AGENTS.md](tests/AGENTS.md) |

## Backtest

Uses Alpaca Data API bars (default **5Min** IEX, `adjustment=all`), cached in SQLite (`data/bars.sqlite`) with **timeframe segregation**. Replays `rebalance_tick` with `SimBroker` once per RTH bar (coarser than live 1-minute loop). Requires same `.env` API keys as paper/live for `fetch`; `run` is read-only on cache.

**Live:** `scheduler.bot_loop` → `maintain_open_limits` (limit poll/cancel) then `bot()` → snapshot VWAPs → `rebalance_tick` with `LiveBroker` (same hysteresis path as backtest). Tick summary logs at INFO (backtest stays DEBUG).

**TUI:** tab `7` (Backtest) — fetch, run comparison, comparison table; Settings is `8`. Key `f` / Positions “Force balance…” = RTH one-shot equal-$ rebalance for one ticker (no hysteresis). Key `w` / “Write off…” = quarantine an untradable orphan (no order).

```bash
python -m backtest fetch --start 2025-01-01 --end 2025-03-01
python -m backtest status
python -m backtest run --start 2025-01-01 --end 2025-03-01 --cash 100000 --margins 0.03,0.05
```

`ticker_source.py` also scrapes SlickCharts **Weight %** into `data/backtest_weights.json` during fetch.

Backtest fetch/run logging uses `backtest.log` (`BACKTEST_LOG_FILE`); `backtest/logging_setup.py` keeps those records out of `alpaca_bot.log` during TUI runs.

## Conventions

- **Secrets:** Never log API keys; keep `.env` out of git.
- **Trades:** Filled trades append to `trades.jsonl` (P/L history). Non-fill order events append to `orders.jsonl`. Do not rely on `trading_state.json` for history. Analytics Unreal P/L is log+state mark (`held×price − (buy$ − sell$)`); leavers absent from state are closed in Unreal; TUI Alpaca refresh is an accuracy check only. Orphan liquidates log qty + pre-close market value.
- **Remote:** Default `REMOTE_LOGGING_ENABLED=false`; `REMOTE_BASE_URL` is the full webhook URL; optional `REMOTE_WEBHOOK_SECRET` for HMAC. Event type in `X-Event-Type` (`trade`, `day_end`, `log`). Remote calls must not raise into the scheduler.
- **State:** `load_state()` raises if the file is missing. CLI/TUI may call `Status.bootstrap` explicitly on first run (`bot.py` auto-creates; TUI Settings / `--init` also). Persists `cash` from Alpaca account polls alongside equity.
- **Tests:** `pytest` from project root; `requirements-dev.txt` for dev deps.
- **VERSION:** `.env` must be `PAPER` or `LIVE` only.

## Principles

- YAGNI; reuse `rebalance_tick` + `Broker`; no new deps if avoidable; deletion over abstraction.
- Clean breaks over shims when changing cache/schema (wipe bars DB if needed).
- Mark deliberate ceilings with `ponytail:` comments (upgrade path named).

## Gotchas

- Orphan leavers are closed via hourly `check_balances` (`DELETE /positions/{symbol}`), not `rebalance_tick`. Failed closes on permanently untradable assets are **quarantined** (no hourly retry spam; MV excluded from equal-weight targets). Clear with CA settlement (auto) or `python bot.py --write-off SYMBOL` / TUI `w`.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys
python bot.py          # headless
python -m tui          # terminal UI
```

TUI uses `setup_logging(..., console=False, default_log_file="alpaca_bot.log")` so logs do not corrupt the screen. Log parsing/filtering: `log_viewer.py`. CLI: `bot.py -v`, `-q`, `--log-level`.

**TUI over SSH/tmux:** Prefer UTF-8 (`LANG=en_US.UTF-8`, `tmux -u`). Set `ALPACA_TUI_ASCII=1` for ASCII activity bars if Unicode renders poorly. Refresh is tab-scoped with conditional Static updates (`tui/ui_refresh.py`) to reduce flicker.

## Index

- [tests/AGENTS.md](tests/AGENTS.md)
- [tui/AGENTS.md](tui/AGENTS.md)
- [backtest/AGENTS.md](backtest/AGENTS.md)
