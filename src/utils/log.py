#!/usr/bin/env python3
# Custom logging function

# Import repo-converter modules
from utils import secret
from utils.context import Context

# Import Python standard modules
from datetime import datetime
import logging


def log(ctx: Context, message, level_name: str = "DEBUG") -> None:

    # level_int
    level_name = str(level_name).upper()

    if level_name in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
        level_int = logging.getLevelName(level_name)
    else:
        level_name = "DEBUG"
        level_int = logging.DEBUG

    # log_message
    log_message = ""

    date_string = datetime.now().date().isoformat()
    time_string = datetime.now().time().isoformat()
    log_message += f"{date_string}; {time_string}; "

    build_tag   = ctx.env_vars["BUILD_TAG_OR_COMMIT_FOR_LOGS"]
    log_message += f"{build_tag}; {ctx.container_id}; "

    run_string  = f"run {ctx.run_count}"
    message     = secret.redact(ctx, message)
    log_message += f"{run_string}; {level_name}; {str(message)}"

    logging.log(level_int, log_message)
