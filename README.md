# Alpaca_bot

Personal saving and investment bot that rebalances a portfolio of NASDAQ-100–derived tickers toward equal notional exposure on the Alpaca API (paper or live).

## Features

- **Ticker source:** Builds the universe from [SlickCharts NASDAQ-100](https://www.slickcharts.com/nasdaq100), filtered for Alpaca-tradable, fractionable, active assets (excluding PTP exceptions).
- **Rebalance logic:** Targets equal notional value per ticker with a configurable margin; buys/sells to bring positions back within the band; uses limit orders when the market is in extended hours.
- **Paper and live:** Switch via `VERSION` in `.env`; uses Alpaca paper or live API and keys accordingly.
- **Extended hours:** Supports pre/post market; places limit orders when the main session is closed.
- **State:** Persists tickers, equity, market state, and open limit orders in `trading_state.json`.
- **Optional remote logging/recording:** Can post logs and daily records to external endpoints (bmd-studios.com); bot continues if those calls fail.

## Requirements

- Python 3.9+
- Dependencies in `requirements.txt`: python-dotenv, requests, beautifulsoup4, requests-ratelimiter, schedule

## Setup

1. **Virtual environment (recommended):**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Environment variables:** Create a `.env` file in the project root. **Do not commit `.env`** (it is in `.gitignore`). Use the exact variable names the code expects:

   | Variable       | Description |
   |----------------|-------------|
   | `VERSION`      | `PAPER` for paper trading, any other value (e.g. `real`) for live. |
   | `PAPER_KEY`    | Alpaca paper API key (used when `VERSION=PAPER`). |
   | `PAPER_SECRET` | Alpaca paper API secret (used when `VERSION=PAPER`). |
   | `API_KEY`      | Alpaca live API key (used when not paper). |
   | `API_SECRET`   | Alpaca live API secret (used when not paper). |
   | `MARGIN`       | Rebalance margin (float). Recommended range 0.02–0.15. |

   Example (no real values):
   ```
   VERSION=PAPER
   PAPER_KEY=your_paper_key
   PAPER_SECRET=your_paper_secret
   API_KEY=your_live_key
   API_SECRET=your_live_secret
   MARGIN=0.05
   ```
   Consider adding a `.env.example` with these keys and placeholder values for contributors.

3. **Optional:** The bot posts logs and daily records to bmd-studios.com. If those endpoints are down or you don’t use them, the bot still runs; failed posts are printed and execution continues.

## Run

```bash
python bot.py
```

Scheduled jobs: every 1 minute (main bot loop), every 1 hour (balance check), and daily at 22:00 (day-end recording).

## Project layout

| Path                | Description |
|---------------------|-------------|
| `bot.py`            | Main entrypoint: config, state, Alpaca client, ticker scraping, rebalance logic, and scheduler. |
| `indicators.py`     | Helper functions `beta()` and `trend()` (RSI/SMA); not currently used by `bot.py`. |
| `requirements.txt`  | Python dependencies. |
| `.env`              | Local env vars (create from names above; do not commit). |
| `trading_state.json`| Generated at runtime; persisted state and open orders. |

---

## Problems and improvements

Use this list to bring the app up to professional standards incrementally.

### Architecture and structure

- [ ] **Modularize:** Split the 606-line monolith into modules (e.g. `config`, `state`, `alpaca_client`, `ticker_source`, `rebalance`, `scheduler`, thin `main`/`bot_loop`).
- [ ] **Remove globals:** Pass `session`, `config`, and `server` explicitly (or via a small context) instead of using globals in `bmd_logger`, `find_tickers`, etc.
- [ ] **Validate config:** Add validated config (e.g. dataclass or Pydantic) with clear errors for missing/invalid `.env` keys; consider `.env.example`.
- [ ] **Dead code:** Either use `indicators.py` from `bot.py` or remove it; remove unused `math` import from `bot.py`.
- [ ] **Deprecated import:** Replace `from requests.packages.urllib3.util.retry import Retry` with `from urllib3.util.retry import Retry`.

### Error handling and resilience

- [ ] **Stop swallowing exceptions:** In `@bmd_logger`, log then re-raise (or set a failure state and exit) so the process can be supervised; avoid silent continuation after critical failures.
- [ ] **Missing state file:** In `__main__`, handle `FileNotFoundError` from `load_state()` explicitly; bootstrap new state or exit with instructions instead of overwriting with empty state.
- [ ] **API/network failures:** Add structured retries, backoff, and clear handling for `get_balances`, `create_order`, `find_tickers` instead of only printing and continuing.
- [ ] **Return conventions:** Use consistent return types (e.g. Result types or exceptions) and type hints; replace string returns like `"success"` / `"failed"` with explicit types.

### Logging and observability

- [ ] **Use standard logging:** Replace `print` with `logging` (INFO for status, WARNING/ERROR for failures); add optional file/rotation.
- [ ] **Remote logging:** Make remote logging (bmd-studios.com) optional and configurable via env.
- [ ] **Sensitive data:** Ensure API keys and secrets are never logged; avoid logging full request/response bodies.

### Self-documentation and maintainability

- [ ] **Docstrings:** Add docstrings to all public functions and classes (e.g. `create_order`, `get_account`, `check_time`, `bot`); include args, returns, and raised exceptions where non-obvious.
- [ ] **Type hints:** Add type hints for public and key internal functions (config, account, order results).
- [ ] **Magic numbers:** Extract and name constants (e.g. limit-order cancel after 300s, limit price offsets 1.005/0.995, sleep 61200s for holiday); document intent.

### Testing and CI

- [ ] **Unit tests:** Add tests for rebalance math, state load/save, and config parsing.
- [ ] **Integration tests:** Add tests against Alpaca paper API (mocked or sandbox) where appropriate.
- [ ] **CI:** Run the test suite in CI on commit or PR.

### Security and operations

- [ ] **Secrets:** Keep `.env` out of version control; document `.env.example` with placeholder keys only.
- [ ] **External endpoints:** Document dependency on bmd-studios.com and slickcharts.com; add timeouts/retries and graceful degradation when unreachable.
- [ ] **Rate limits:** Document Alpaca API rate limits; note that `LimiterSession` applies to Alpaca; scraping (SlickCharts) is separate.

### Other

- [ ] **Schedule robustness:** Single-threaded `schedule` can be delayed by long-running `bot()` or blocking I/O; consider non-blocking or worker design if scaling.
- [ ] **Python version:** Pin in README (e.g. 3.9+) and optionally in `requires-python` (e.g. in `pyproject.toml` or setup metadata).
- [ ] **AGENTS.md:** Project rules reference AGENTS.md; add a high-level AGENTS.md so the repo matches project conventions.
