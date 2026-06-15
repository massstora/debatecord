from __future__ import annotations

import argparse
import logging

from .bot import run_bot
from .config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Debatecord Discord bot.")
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to the TOML config file. Defaults to config.toml.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)
    run_bot(config)


if __name__ == "__main__":
    main()

