# Alpaca_bot — agent guide

Personal NASDAQ-100 equal-weight rebalancer on Alpaca (paper or live).

## Layout

| Module | Role |
|--------|------|
| `bot.py` | Headless CLI entry point |
| `runner.py` | `BotRunner` — threaded scheduler, start/stop |
| `tui/` | Textual TUI (`python -m tui`) |
| `analytics.py` | Trade/portfolio stats from `trades.jsonl` |
| `env_config.py` | `.env` margin read/write |
| `config.py` | `.env` loading and validation |
| `state.py` | `Status` and `trading_state.json` |
| `alpaca_client.py` | HTTP session, account, positions |
| `ticker_source.py` | SlickCharts scrape + Alpaca asset filter |
| `market.py` | Market clock, extended hours, holidays |
| `rebalance.py` | Core rebalance loop |
| `orders.py` | `create_order`, `OrderResult`, trade logging hooks |
| `trade_log.py` | Append-only `trades.jsonl` |
| `remote.py` | Optional bmd-studios.com HTTP (env-gated) |
| `reporting.py` | Daily record and check-in payloads |
| `scheduler.py` | `bot_loop`, `bmd_logger`, hourly balance check |
| `utils.py` | `trunc()` |

## Conventions

- **Secrets:** Never log API keys; keep `.env` out of git.
- **Trades:** Always append to `trades.jsonl`; do not rely on `trading_state.json` for history.
- **Remote:** Default `REMOTE_LOGGING_ENABLED=false`; remote calls must not raise into the scheduler.
- **State:** Missing `trading_state.json` exits with an error (no silent empty bootstrap).
- **Tests:** `pytest` from project root; `requirements-dev.txt` for dev deps.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys
python bot.py          # headless
python -m tui          # terminal UI
```

TUI uses `setup_logging(..., console=False, default_log_file="alpaca_bot.log")` so logs do not corrupt the screen. Log parsing/filtering: `log_viewer.py`. CLI: `bot.py -v`, `-q`, `--log-level`.
