#!/usr/bin/env python3
# Custom logging functionality

# Import repo-converter modules
from utils import secret
from utils.context import Context

# Import Python standard modules
from datetime import datetime
from sys import stdout
import logging


def configure_logging(ctx: Context) -> None:

    level_name = ctx.env_vars["LOG_LEVEL"]

    if level_name not in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
        level_name = "INFO"

    logging.basicConfig(
        stream      = stdout,
        datefmt     = "%Y-%m-%d %H:%M:%S",
        encoding    = "utf-8",
        format      = f"%(message)s",
        level       = level_name
    )


def log(ctx: Context, message, level_name: str = "DEBUG") -> None:

    level_name = str(level_name).upper()

    if level_name in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
        level_int = logging.getLevelName(level_name)
    else:
        level_name = "DEBUG"
        level_int = logging.DEBUG

    date_string = datetime.now().date().isoformat()
    time_string = datetime.now().time().isoformat()
    log_message = f"{date_string}; {time_string}; "

    # TODO: Test this
    build_tag   = ""
    if ctx.env_vars["BUILD_TAG"]:
        build_tag = ctx.env_vars["BUILD_TAG"]
    elif ctx.env_vars["BUILD_COMMIT"]:
        build_tag = ctx.env_vars["BUILD_COMMIT"]
    if build_tag:
        log_message += f"{build_tag}; "

    run_string  = f"run {ctx.run_count}"
    message     = secret.redact(ctx, message)

    log_message += f"{run_string}; {level_name}; {str(message)}"

    logging.log(level_int, log_message)
