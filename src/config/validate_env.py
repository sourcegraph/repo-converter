#!/usr/bin/env python3
# Validate environment variables

# Import repo-converter modules
from utils.context import Context
from utils.log import log


def validate_env_vars(ctx: Context) -> None:
    """Validate inputs here, now that the logger is instantiated, instead of throughout the code"""

    # Leave the exception handling to the interpreter, the container should fail to start up if an exception is raised

    # Validate concurrency limits
    if ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_PER_SERVER"] <= 0:
        raise ValueError("MAX_CONCURRENT_CONVERSIONS_PER_SERVER must be greater than 0")

    if ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_TOTAL"] <= 0:
        raise ValueError("MAX_CONCURRENT_CONVERSIONS_TOTAL must be greater than 0")

    if ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_PER_SERVER"] > ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_TOTAL"]:

        log(ctx, f"MAX_CONCURRENT_CONVERSIONS_PER_SERVER={ctx.env_vars['MAX_CONCURRENT_CONVERSIONS_PER_SERVER']} is greater than MAX_CONCURRENT_CONVERSIONS_TOTAL={ctx.env_vars['MAX_CONCURRENT_CONVERSIONS_TOTAL']}, MAX_CONCURRENT_CONVERSIONS_PER_SERVER limit will not be hit", "WARNING")

    return None
