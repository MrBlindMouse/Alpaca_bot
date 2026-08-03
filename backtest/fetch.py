"""Download Alpaca historical bars into SQLite."""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

from alpaca_client import create_data_session, fetch_stock_bars_pages
from backtest.cache import BarCache, BarRow
from backtest.config import BacktestConfig, load_trading_config
from backtest.universe import load_universe
from config import Config

logger = logging.getLogger("alpaca_bot.backtest.fetch")


def _normalize_range_start(start: str) -> str:
    if "T" in start:
        return start
    return f"{start}T00:00:00Z"


def _normalize_range_end(end: str) -> str:
    if "T" in end:
        return end
    return f"{end}T23:59:59Z"


def _bar_rows(symbol: str, bars: list) -> List[BarRow]:
    rows: List[BarRow] = []
    for bar in bars:
        ts = bar.get("t")
        if not ts:
            continue
        rows.append(
            (
                symbol,
                ts,
                float(bar["o"]),
                float(bar["h"]),
                float(bar["l"]),
                float(bar["c"]),
                float(bar.get("v") or 0),
                float(bar["vw"]) if bar.get("vw") is not None else None,
            )
        )
    return rows


def fetch_symbol(
    session,
    config: Config,
    cache: BarCache,
    symbol: str,
    range_start: str,
    range_end: str,
    bt_cfg: BacktestConfig,
    *,
    force: bool = False,
) -> int:
    if not force and cache.is_fetched(
        symbol,
        range_start,
        range_end,
        timeframe=bt_cfg.timeframe,
    ):
        logger.info("Skip %s (already fetched %s .. %s)", symbol, range_start, range_end)
        return 0

    if force:
        cache.clear_fetch_log(
            symbol, range_start, range_end, timeframe=bt_cfg.timeframe
        )
        cache.clear_bars(
            symbol, range_start, range_end, timeframe=bt_cfg.timeframe
        )

    total = 0
    page_num = 0
    for page in fetch_stock_bars_pages(
        session,
        config,
        symbol,
        start=range_start,
        end=range_end,
        timeframe=bt_cfg.timeframe,
        feed=bt_cfg.feed,
        adjustment=bt_cfg.adjustment,
    ):
        page_num += 1
        rows = _bar_rows(symbol, page)
        total += cache.upsert_bars(rows, timeframe=bt_cfg.timeframe)
        logger.debug("%s page %s: %s bars", symbol, page_num, len(rows))

    cache.mark_fetched(
        symbol,
        range_start,
        range_end,
        total,
        timeframe=bt_cfg.timeframe,
    )
    logger.info("Fetched %s: %s bars (%s pages)", symbol, total, page_num)
    return total


def fetch_all(
    bt_cfg: BacktestConfig,
    *,
    start: str,
    end: str,
    symbols: Optional[List[str]] = None,
    force: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    range_start = _normalize_range_start(start)
    range_end = _normalize_range_end(end)
    trading_cfg = load_trading_config()
    session = create_data_session(per_minute=bt_cfg.data_rpm)
    cache = BarCache(bt_cfg.bar_db)

    if symbols is None:
        symbols, _weights = load_universe(
            trading_cfg,
            session,
            symbols_file=bt_cfg.symbols_file,
            weights_file=bt_cfg.weights_file,
        )

    total_bars = 0
    failed_symbols: List[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        logger.info("Symbol %s/%s: %s", idx, len(symbols), symbol)
        try:
            count = fetch_symbol(
                session,
                trading_cfg,
                cache,
                symbol,
                range_start,
                range_end,
                bt_cfg,
                force=force,
            )
            total_bars += count
            if on_progress:
                on_progress(f"{idx}/{len(symbols)} {symbol}: {count} bars")
        except Exception as exc:
            logger.error("Failed %s: %s", symbol, exc)
            failed_symbols.append(symbol)
            if on_progress:
                on_progress(f"{idx}/{len(symbols)} {symbol}: FAILED {exc}")
        if bt_cfg.symbol_delay_ms > 0 and idx < len(symbols):
            time.sleep(bt_cfg.symbol_delay_ms / 1000.0)

    return {
        "symbols": len(symbols),
        "bars_inserted": total_bars,
        "failed_symbols": failed_symbols,
        **cache.status(),
    }
