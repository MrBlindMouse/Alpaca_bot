# Alpaca_bot

Personal saving and investment bot that rebalances a portfolio of NASDAQ-100–derived tickers toward equal notional exposure on the Alpaca API (paper or live).

## Features

- **Ticker source:** Builds the universe from [SlickCharts NASDAQ-100](https://www.slickcharts.com/nasdaq100), filtered for Alpaca-tradable, fractionable, active assets (excluding PTP exceptions).
- **Rebalance logic:** Targets equal notional value per ticker with a configurable margin; buys/sells to bring positions back within the band; uses limit orders when the market is in extended hours.
- **Paper and live:** Switch via `VERSION` in `.env`; uses Alpaca paper or live API and keys accordingly.
- **Extended hours:** Supports pre/post market; places limit orders when the main session is closed.
- **State:** Persists tickers, equity, market state, and open limit orders in `trading_state.json`.
- **Trade log:** Every order and liquidation is appended to `trades.jsonl` for offline analysis.
- **Optional remote logging/recording:** When `REMOTE_LOGGING_ENABLED=true`, posts logs, heartbeats, and daily records to bmd-studios.com (or `REMOTE_BASE_URL`). Default is off; failures never stop the bot.

## Requirements

- Python 3.9+
- Dependencies in `requirements.txt`: python-dotenv, requests, beautifulsoup4, requests-ratelimiter, schedule, textual

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
   | `VERSION` | `PAPER` for paper trading, any other value (e.g. `real`) for live. |
   | `PAPER_KEY` / `PAPER_SECRET` | Alpaca paper credentials (when `VERSION=PAPER`). |
   | `API_KEY` / `API_SECRET` | Alpaca live credentials (when not paper). |
   | `MARGIN` | Rebalance margin (float). Recommended range 0.02–0.15. |
   | `REMOTE_LOGGING_ENABLED` | `true` to enable remote posts; default `false`. |
   | `REMOTE_BASE_URL` | Base URL for remote endpoints (default `https://www.bmd-studios.com`). |
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

Scheduled jobs: every 1 minute (main bot loop), every 1 hour (balance check), and daily at 22:00 (day-end recording when remote logging is enabled).

| Key | Action |
|-----|--------|
| `t` | Toggle start/stop bot |
| `r` | Refresh state, trades, and Alpaca data (Logs tab reloads from file) |
| `q` | Quit (prompts if bot is running) |
| `1` | Dashboard |
| `2` | Positions |
| `3` | Trades |
| `4` | Analytics |
| `5` | Logs |
| `6` | Settings |

Use the **tab bar** or footer keys `1`–`6` to switch views. The status bar also shows the active view name.

**Status bar:** **Bot tick** is the last scheduler rebalance (~1 min while running). **UI updated** (on the Dashboard) is when the TUI last read local state/logs (~every 2 s).

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
| `rebalance.py` | Rebalance loop |
| `orders.py` | Order placement and `OrderResult` |
| `trade_log.py` | Append-only `trades.jsonl` |
| `remote.py` | Optional remote HTTP client |
| `reporting.py` | Daily record and check-in |
| `scheduler.py` | `bot_loop` and decorators |
| `requirements.txt` | Runtime dependencies |
| `requirements-dev.txt` | pytest (development) |
| `.env` | Local secrets (not committed) |
| `trading_state.json` | Runtime operational state |
| `trades.jsonl` | Runtime trade history (not committed) |

See [AGENTS.md](AGENTS.md) for a concise map for contributors and coding agents.

## Trade analysis

All trades are written to `trades.jsonl` (one JSON object per line). Example queries:

```bash
# Pretty-print all trades
cat trades.jsonl | jq .

# Filled buys only
jq 'select(.status == "filled" and .side == "buy")' trades.jsonl

# Count by symbol
jq -r .symbol trades.jsonl | sort | uniq -c
```

In Python:

```python
import json
trades = [json.loads(line) for line in open("trades.jsonl")]
```

## Analytics tab (TUI)

The **Analytics** tab combines `trades.jsonl` (filtered by period) with `trading_state.json` and optional Alpaca refresh.

| Column | Meaning |
|--------|---------|
| **Price** | Current share price from Alpaca positions after refresh, otherwise from `trading_state.json`. |
| **Trading P/L** | `(sell $ − buy $) + (net rebalance qty × current price)` for **filled** rebalance trades (`rebalance_buy`, `rebalance_sell`, `rebalance`) in the period. Excludes initial buys (`rebalance_initial`) and orphan liquidations (`liquidate`). `—` when there were no rebalance fills for that symbol. Summary line shows the portfolio total. |
| **Unreal. P/L** | Alpaca `market_value − cost_basis` after **Refresh from Alpaca**. |
| **Swing %** | How far the position is from the bot’s equal-weight target (rebalance band), not daily stock return. |

Summary **Avg Net $** is the per-ticker rebalance target: `equity ÷ (ticker_count + ticker_count×margin÷2)` (same as the live rebalance loop).

**Trade activity** (footer chart) ranks symbols by **filled** trade count in the period, not failed or limit-placed orders.

Use period **All** for a full trading P/L picture; shorter windows only include rebalance fills logged in that range.

Click a **column header** to sort (click again to reverse).

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

CI runs pytest on Python 3.9, 3.11, and 3.12 (see `.github/workflows/test.yml`).

## External dependencies

- **Alpaca** — trading, clock, calendar, positions, market data
- **SlickCharts** — NASDAQ-100 constituent list (scraped)
- **bmd-studios.com** — optional remote logging/recording (off by default)

Alpaca API calls use `LimiterSession` (200/min). Scraping is separate and not rate-limited by that session.

## Remaining improvements

The bot is modular with tests and optional remote logging. Possible follow-ups:

- Integration tests against Alpaca paper API (mocked HTTP)
- Richer rebalance unit tests (margin band math)
- Non-blocking scheduler if loop latency becomes an issue
