"""CLI: python -m backtest fetch|run|status"""

from __future__ import annotations

import argparse
import sys

from backtest.config import BacktestConfig, load_backtest_config
from backtest.logging_setup import setup_backtest_cli_logging
from backtest.service import (
    cache_status_dict,
    execute_comparisons,
    execute_fetch,
    parse_margins,
)


def _cmd_fetch(args: argparse.Namespace, bt_cfg: BacktestConfig) -> int:
    start = args.start or bt_cfg.start
    end = args.end or bt_cfg.end
    if not start or not end:
        print("fetch requires --start and --end (or BACKTEST_START/BACKTEST_END in .env)")
        return 1
    result = execute_fetch(bt_cfg, start, end, force=args.force)
    print(
        f"Done: {result['symbols']} symbols, {result['bars_inserted']} bars inserted, "
        f"cache has {result['bar_count']} bars for {result['symbol_count']} symbols"
    )
    print(f"  Log: {bt_cfg.log_file}")
    return 0


def _cmd_status(args: argparse.Namespace, bt_cfg: BacktestConfig) -> int:
    st = cache_status_dict(bt_cfg)
    print(f"Database: {st['db']}")
    print(f"Bars: {st['bar_count']}")
    print(f"Symbols: {st['symbol_count']}")
    print(f"Fetch ranges logged: {st['fetch_ranges']}")
    print(f"Time range: {st['min_ts']} .. {st['max_ts']}")
    return 0


def _cmd_run(args: argparse.Namespace, bt_cfg: BacktestConfig) -> int:
    start = args.start or bt_cfg.start
    end = args.end or bt_cfg.end
    if not start or not end:
        print("run requires --start and --end (or BACKTEST_START/BACKTEST_END in .env)")
        return 1
    cash = args.cash if args.cash is not None else bt_cfg.initial_cash
    margins_raw = args.margins or bt_cfg.margins
    margins = parse_margins(margins_raw)

    results = execute_comparisons(
        bt_cfg,
        start,
        end,
        cash,
        margins,
        primary_margin=margins[0],
    )
    print("Comparison complete")
    print(f"  Wrote: {bt_cfg.comparison_file}")
    print(f"  Primary equity: {bt_cfg.equity_file}")
    print(f"  Primary trades: {bt_cfg.trades_file}")
    print(f"  Log: {bt_cfg.log_file}")
    for row in results:
        print(
            f"  {row.strategy:28} margin={row.margin_label():6} "
            f"return={row.total_return_pct:7.2f}% dd={row.max_drawdown_pct:7.2f}% "
            f"trades={row.trade_count}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alpaca_bot historical backtest")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Download bars into SQLite cache")
    p_fetch.add_argument("--start", help="Start date YYYY-MM-DD or ISO8601")
    p_fetch.add_argument("--end", help="End date YYYY-MM-DD or ISO8601")
    p_fetch.add_argument("--force", action="store_true", help="Re-fetch even if logged")

    sub.add_parser("status", help="Show cache statistics")

    p_run = sub.add_parser("run", help="Run comparison backtest from cache")
    p_run.add_argument("--start", help="Start date YYYY-MM-DD or ISO8601")
    p_run.add_argument("--end", help="End date YYYY-MM-DD or ISO8601")
    p_run.add_argument("--cash", type=float, help="Initial cash")
    p_run.add_argument(
        "--margins",
        help="Comma-separated rebalance margins (default BACKTEST_MARGINS or MARGIN)",
    )

    args = parser.parse_args(argv)
    bt_cfg = load_backtest_config()
    setup_backtest_cli_logging(bt_cfg, verbose=args.verbose)

    if args.command == "fetch":
        return _cmd_fetch(args, bt_cfg)
    if args.command == "status":
        return _cmd_status(args, bt_cfg)
    if args.command == "run":
        return _cmd_run(args, bt_cfg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
