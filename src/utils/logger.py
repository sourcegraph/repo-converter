#!/usr/bin/env python3
# Custom logging functionality

# Import repo-converter modules
from utils import secret

# Import Python standard modules
from datetime import datetime
from sys import stdout
import logging


def configure_logging(level_name:str = "INFO"):

    logging.basicConfig(
        stream      = stdout,
        datefmt     = "%Y-%m-%d %H:%M:%S",
        encoding    = "utf-8",
        format      = f"%(message)s",
        level       = level_name
    )


def log(message, level_name:str = "DEBUG"):

    level_name = str(level_name).upper()

    if level_name in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
        level_int = logging.getLevelName(level_name)
    else:
        level_name = "DEBUG"
        level_int = logging.DEBUG

    date_string = datetime.now().date().isoformat()
    time_string = datetime.now().time().isoformat()
    run_string  = ""# f"run {str(script_run_number)}"
    message     = secret.redact(message)
    log_message = f"{date_string}; {time_string}; {run_string}; {level_name}; {str(message)}"

    logging.log(level_int, log_message)

