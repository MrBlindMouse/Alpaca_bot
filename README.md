# Alpaca_bot

Personal saving and investment bot that rebalances a portfolio of NASDAQ-100–derived tickers toward equal notional exposure on the Alpaca API (paper or live).

## Features

- **Ticker source:** Builds the universe from [SlickCharts NASDAQ-100](https://www.slickcharts.com/nasdaq100), filtered for Alpaca-tradable, fractionable, active assets (excluding PTP exceptions).
- **Rebalance logic:** Targets equal notional value per ticker with a configurable margin; buys/sells to bring positions back within the band; uses limit orders when the market is in extended hours.
- **Paper and live:** Switch via `VERSION` in `.env`; uses Alpaca paper or live API and keys accordingly.
- **Extended hours:** Supports pre/post market; places limit orders when the main session is closed.
- **State:** Persists tickers, equity, cash, market state, and open limit orders in `trading_state.json`.
- **Trade log:** Filled trades append to `trades.jsonl` (P/L). Non-fill order lifecycle events append to `orders.jsonl`.
- **Optional remote webhook:** When `REMOTE_LOGGING_ENABLED=true`, POSTs trade fills, day-end equity, and WARNING+ logs to `REMOTE_BASE_URL` with optional HMAC (`REMOTE_WEBHOOK_SECRET`). Default is off; failures never stop the bot.

## Requirements

- Python 3.9+
- Dependencies in `requirements.txt`: python-dotenv, requests, beautifulsoup4, requests-ratelimiter, textual

## Setup

1. **Virtual environment (recommended):**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Environment variables:** Copy [`.env.example`](.env.example) to `.env` and fill in values. **Do not commit `.env`.**

   | Variable | Description |
   |----------|-------------|
   | `VERSION` | `PAPER` or `LIVE` only (validated at startup). |
   | `PAPER_KEY` / `PAPER_SECRET` | Alpaca paper credentials (when `VERSION=PAPER`). |
   | `API_KEY` / `API_SECRET` | Alpaca live credentials (when `VERSION=LIVE`). |
   | `MARGIN` | Rebalance margin (float). Recommended range 0.02–0.15. |
   | `REMOTE_LOGGING_ENABLED` | `true` to enable webhook posts; default `false`. |
   | `REMOTE_BASE_URL` | Full webhook URL (required when enabled). |
   | `REMOTE_WEBHOOK_SECRET` | Shared secret for `X-Signature-256` HMAC-SHA256 of the body; empty = unsigned. |
   | `LOG_LEVEL` | Standard logging level (default `INFO`). |
   | `LOG_FILE` | Optional path for rotating log file (leave empty for console only). |

3. **First run:** If `trading_state.json` is missing, the TUI creates it automatically when you open `python -m tui`. Headless mode creates it on startup, or run `python bot.py --init` to create the file only.

## Run

**Headless bot** (scheduler in foreground):

```bash
python bot.py
```

**Terminal UI** (start/stop bot, margin, live status, analytics):

```bash
python -m tui
```

Bot logs go to `alpaca_bot.log` when using the TUI (console logging is disabled so the UI stays readable). Set `LOG_FILE` in `.env` to customize.

Scheduler: adaptive bot tick (60s when open/extended, up to 30m when closed), hourly balance check, day-end at 22:00 America/New_York (posted to the webhook when remote logging is enabled).

| Key | Action |
|-----|--------|
| `t` | Toggle start/stop bot |
| `r` | Refresh state/trades; run Alpaca accuracy check (Logs tab reloads from file) |
| `q` | Quit (prompts if bot is running) |
| `1` | Dashboard |
| `2` | Positions |
| `3` | Trades |
| `4` | Analytics |
| `5` / `6` | Logs |
| `7` | Backtest |
| `8` | Settings |

Use the **tab bar** or footer keys `1`–`5`, `7`, and `8` to switch views. The status bar also shows the active view name.

**Status bar:** **Bot tick** is the last scheduler loop completion (about every 1 min when the market is open/extended, less often when closed). **UI updated** (on the Dashboard) is when the TUI last read local state/logs (every 2 s while the bot runs or on Logs/Backtest; otherwise about every 5 s for the active tab only).

**SSH / tmux:** Use UTF-8 (`export LANG=en_US.UTF-8`, start tmux with `tmux -u`). If bar charts or borders look wrong, run `ALPACA_TUI_ASCII=1 python -m tui` for ASCII activity bars.

On the **Logs** tab, new lines are appended without clearing the viewer (scroll position is preserved). Press `r` to reload the full log window.

**Tables:** Click a column header to sort. Numeric columns sort by value, not as text. **Trades** rows use a muted green (buy) or blue-gray (sell) tint. **Analytics** rows use a muted green/red tint by trading P/L sign.

![TUI screenshot](docs/tui-screenshot.png)

### Logging

**Headless** (`python bot.py`):

| Flag | Effect |
|------|--------|
| `-v` / `--verbose` | DEBUG |
| `-q` / `--quiet` | WARNING and above |
| `--log-level debug` | Explicit level (debug, info, warning, error, critical) |
| `--log-file PATH` | Also write to a rotating log file |

`.env` `LOG_LEVEL` applies when no CLI flag is set. Example: `python bot.py -v --log-file alpaca_bot.log`

**TUI** (`python -m tui`): logs go to `alpaca_bot.log` (or `LOG_FILE`). Open the **Logs** tab to filter by level and change what the bot writes. Same CLI flags: `python -m tui -v`.

Dashboard shows the last few WARNING+ lines; the Logs tab shows up to 400 lines with color by level.

## Project layout

| Path | Description |
|------|-------------|
| `bot.py` | Headless CLI entry point |
| `runner.py` | `BotRunner` start/stop scheduler (CLI + TUI) |
| `tui/` | Textual terminal UI (`python -m tui`) |
| `analytics.py` | Trade/portfolio aggregates for TUI |
| `env_config.py` | Read/write `MARGIN` in `.env` |
| `config.py` | Environment loading and validation |
| `state.py` | `trading_state.json` load/save |
| `alpaca_client.py` | Alpaca HTTP session and account/positions |
| `ticker_source.py` | NASDAQ-100 ticker discovery |
| `market.py` | Market clock and session state |
| `rebalance.py` | Shared `rebalance_tick`, limit maintain, live `bot()` |
| `broker.py` / `live_broker.py` | Broker protocol and Alpaca adapter |
| `resilience.py` | Circuit breaker |
| `orders.py` | Order placement and `OrderResult` |
| `trade_log.py` | Append-only `trades.jsonl` (fills) / `orders.jsonl` (non-fills) |
| `remote.py` | Optional HMAC webhook client (`post_event`) |
| `reporting.py` | Day-end equity record |
| `scheduler.py` | `bot_loop` and hourly balance check |
| `backtest/` | Historical replay (`python -m backtest`) |
| `log_viewer.py` / `utils.py` | Log parsing helpers / `trunc()` |
| `requirements.txt` | Runtime dependencies |
| `requirements-dev.txt` | pytest (development) |
| `.env` | Local secrets (not committed) |
| `trading_state.json` | Runtime operational state |
| `trades.jsonl` | Filled trade history for P/L (not committed) |
| `orders.jsonl` | Non-fill order events (not committed) |

See [AGENTS.md](AGENTS.md) for a concise map for contributors and coding agents.

## Trade analysis

Filled trades go to `trades.jsonl`; failed/limit lifecycle events go to `orders.jsonl`. Example queries:

```bash
# Pretty-print all fills
cat trades.jsonl | jq .

# Filled buys only
jq 'select(.side == "buy")' trades.jsonl

# Count by symbol
jq -r .symbol trades.jsonl | sort | uniq -c
```

In Python:

```python
import json
trades = [json.loads(line) for line in open("trades.jsonl")]
```

## Analytics tab (TUI)

The **Analytics** tab combines `trades.jsonl` (period for Trading P/L; all-time for Unreal cashflow) with `trading_state.json` marks. **Alpaca accuracy check** (button / `r`) loads broker positions/account and shows Unreal/Cash deltas vs the log/state numbers — it does not replace them.

| Column | Meaning |
|--------|---------|
| **Buy $ / Sell $** | Sum of filled notional for the period, excluding initial buys (`rebalance_initial`) and orphan liquidations (`liquidate`). |
| **Value** | `qty × price` from `trading_state.json`. |
| **Trading P/L** | `(sell $ − buy $) + (net rebalance qty × current price)` for **filled** rebalance trades (`rebalance_buy`, `rebalance_sell`, `rebalance`) in the period. Excludes initial buys (`rebalance_initial`) and orphan liquidations (`liquidate`). `—` when there were no rebalance fills for that symbol. Summary line shows the portfolio total. |
| **Unreal. P/L** | `held×price − (buy$ − sell$)` from **all-time** fills (every intent) plus current state mark. Period filter does not apply to the cashflow leg. Symbols absent from `trading_state` (NDX leavers) keep Value `—` and are treated as fully exited for Unreal (historical null liquidate sells are closed at cost). |
| **Swing %** | How far the position is from the bot’s equal-weight target (rebalance band), not daily stock return. |

Summary **Avg Net $** is the per-ticker rebalance target: `equity ÷ (ticker_count + ticker_count×margin÷2)` (same as the live rebalance loop). Orphan liquidates log pre-close qty and market value into `trades.jsonl` for cashflow.

**Trade activity** (footer chart) ranks symbols by **filled** trade count in the period, not failed or limit-placed orders.

Use period **All** for a full trading P/L picture; shorter windows only include rebalance fills logged in that range.

Click a **column header** to sort (click again to reverse).

## Backtest

Historical simulation via Alpaca bars (5Min, IEX, split-adjusted), cached in SQLite. Steps every **5 minutes** during regular US hours (live bot ticks every 1 minute).

```bash
python -m backtest fetch --start 2025-01-01 --end 2025-12-31
python -m backtest status
python -m backtest run --start 2025-01-01 --end 2025-12-31 --cash 100000 --margins 0.03,0.05,0.10
```

**Run comparison** (CLI or TUI tab `7`) runs three strategy families on the same range and cached bars:

| Strategy | Description |
|----------|-------------|
| Equal-wt B&H | Invest `cash / N` in each symbol at the first RTH bar, hold |
| Cap-wt B&H (static NDX wt) | Invest `cash × weight` using current SlickCharts index weights (`data/backtest_weights.json`) — not historical point-in-time weights |
| Rebalancer | Full `rebalance_tick` loop, once per margin in `BACKTEST_MARGINS` or the margins field |

Outputs: `backtest_comparison.csv`, `backtest_equity.csv` / `backtest_trades.jsonl` for the primary margin (detail tables in the TUI). Fetch/run **Python logs** go to `backtest.log` (`BACKTEST_LOG_FILE`), not `alpaca_bot.log`, so live bot logs stay clean when using the TUI. See `.env.example` for `BACKTEST_*` settings. First `fetch` needs network and market-data access on your Alpaca account; `run` uses the cache only.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

## External dependencies

- **Alpaca** — trading, clock, calendar, positions, market data
- **SlickCharts** — NASDAQ-100 constituent list (scraped)
- **Webhook** — optional `REMOTE_BASE_URL` receiver for trade / day_end / log events (off by default)

Alpaca API calls use `LimiterSession` (200/min). Scraping is separate and not rate-limited by that session.

## Remaining improvements

The bot is modular with tests and optional remote logging. Possible follow-ups:

- Integration tests against Alpaca paper API (mocked HTTP)
- Non-blocking scheduler if loop latency becomes an issue
