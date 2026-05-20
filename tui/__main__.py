import argparse
import sys

from config import Config, setup_logging
from log_viewer import add_log_level_args, apply_log_level_args
from tui.app import AlpacaApp


def main():
    parser = argparse.ArgumentParser(description="Alpaca bot terminal UI")
    add_log_level_args(parser)
    args = parser.parse_args()

    config = Config()
    try:
        config.update()
        apply_log_level_args(config, args)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not config.log_file:
        config.log_file = "alpaca_bot.log"
    setup_logging(config, console=False, default_log_file=config.log_file)
    AlpacaApp().run()


if __name__ == "__main__":
    main()
