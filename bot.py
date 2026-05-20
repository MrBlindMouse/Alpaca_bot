"""Entry point for the Alpaca rebalancing bot (headless CLI)."""

import argparse
import logging
import sys

from config import Config, log_remote_disabled_once, setup_logging
from log_viewer import add_log_level_args, apply_log_level_args
from runner import BotRunner
from state import Status

logger = logging.getLogger("alpaca_bot")


def main():
    parser = argparse.ArgumentParser(
        description="Alpaca rebalancing bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Logging examples:
  python bot.py                    # INFO (from .env LOG_LEVEL or default)
  python bot.py -v                 # DEBUG
  python bot.py -q                 # WARNING and above
  python bot.py --log-level debug
  python bot.py --log-file bot.log # also write to file
""",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Create trading_state.json from .env and exit",
    )
    add_log_level_args(parser)
    args = parser.parse_args()

    config = Config()
    try:
        config.update()
        apply_log_level_args(config, args)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(config)
    log_remote_disabled_once(config, logger)
    logger.debug("Logging at %s", config.log_level)

    account = Status()
    if args.init:
        Status.bootstrap(config.margin)
        print(f"Created {Status.STATE_FILE} (margin={config.margin:g})")
        return

    if not Status.state_exists():
        logger.info("No state file; creating initial %s", Status.STATE_FILE)
        account = Status.bootstrap(config.margin)
    else:
        logger.info("Loading account state")
        account.load_state()

    runner = BotRunner(config, account)
    runner.run_forever()


if __name__ == "__main__":
    main()
