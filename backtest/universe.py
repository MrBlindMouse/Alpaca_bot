"""Backtest symbol universe loading."""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from ticker_source import find_tickers, get_cached_valid_tickers, scrape_index_weights

logger = logging.getLogger("alpaca_bot.backtest.universe")


def save_symbols(symbols: List[str], path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump({"symbols": sorted(symbols)}, file, indent=2)


def save_weights(weights: dict, path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump({"weights": weights}, file, indent=2)


def load_weights_from_file(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict) and "weights" in data:
            return {k: float(v) for k, v in data["weights"].items()}
        if isinstance(data, dict):
            return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        pass
    return {}


def ensure_weights(path: str) -> dict:
    cached = load_weights_from_file(path)
    if cached:
        return cached
    weights = scrape_index_weights()
    if weights:
        save_weights(weights, path)
        logger.info("Saved index weights for %s symbols to %s", len(weights), path)
    return weights or {}


def load_symbols_from_file(path: str) -> List[str]:
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list):
            return sorted(data)
        if isinstance(data, dict) and "symbols" in data:
            return sorted(data["symbols"])
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def load_symbols(
    config,
    session,
    *,
    symbols_file: str,
) -> List[str]:
    cached = load_symbols_from_file(symbols_file)
    if cached:
        logger.info("Using %s symbols from %s", len(cached), symbols_file)
        return cached

    tickers = get_cached_valid_tickers()
    if tickers:
        logger.info("Using %s symbols from ticker cache", len(tickers))
        return tickers

    tickers = find_tickers(session, config)
    if not tickers:
        raise RuntimeError(
            "No symbols available. Run with network once to populate "
            f"{symbols_file} or .ticker_cache.json"
        )
    tickers = sorted(tickers)
    return tickers


def load_universe(config, session, *, symbols_file: str, weights_file: str) -> tuple[list, dict]:
    symbols = load_symbols(config, session, symbols_file=symbols_file)
    save_symbols(symbols, symbols_file)
    weights = ensure_weights(weights_file)
    return symbols, weights
