#!/usr/bin/env python3
# Configure logger, without importing Context module

# Import Python standard modules
from sys import stdout
import logging


def configure_logger(log_level: str) -> None:

    level_name = log_level.upper()

    if level_name not in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
        level_name = "INFO"

    logging.basicConfig(
        stream      = stdout,
        datefmt     = "%Y-%m-%d %H:%M:%S",
        encoding    = "utf-8",
        format      = f"%(message)s",
        level       = level_name
    )
