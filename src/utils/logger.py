#!/usr/bin/env python3
# Configure logger, without importing Context module

# Try to use canonical log lines wherever possible, ex. at the end of each run_subprocess execution
# https://brandur.org/canonical-log-lines#what-are-they
# A canonical line is a big log line that gets emitted at the end of a request
# It's filled with all of the fields needed to understand that request's key information

# Also build up logging context throughout the execution process
# https://brandur.org/logfmt#building-context

# Import Python standard modules
from sys import stdout
import logging # Still needed by structlog?

# Import third party modules
import structlog
import json


def configure_logger(log_level: str) -> None:
    """
    Configure structured logging with JSON Lines output format using structlog
    """

    level_name = log_level.upper()

    if level_name not in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
        level_name = "INFO"

    log_level_value = getattr(logging, level_name)

    # Amp:
    # Configure standard library logging - required for structlog stdlib integration
    # Alternatively, could avoid stdlib logging entirely usings
    # logger_factory=structlog.PrintLoggerFactory()
    # But then we'd lose integration with existing Python logging infrastructure that other libraries might use
    # Marc: I don't think we're currently using any other libraries which emit logs?
    logging.basicConfig(
        stream      = stdout,
        level       = level_name,
        format      = "%(message)s"
    )

    # Configure structlog for JSON Lines output
    structlog.configure(
        cache_logger_on_first_use=True,
        logger_factory=structlog.stdlib.LoggerFactory(),
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _custom_json_renderer
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level_value),
    )


def _custom_json_renderer(logger, method_name, event_dict):
    """
    Custom JSON renderer that:
    - Renames keys, ex. 'event' to 'message'
    - Sorts keys at all levels
    """

    # Define the desired key order for top-level keys
    # Any keys not listed here will be sorted alphabetically
    top_level_key_order = [

        # Metadata useful for sorting lines
        "date",
        "time",
        "cycle",

        # Important data
        "message",
        "level",
        "correlation_id",

        # Details in structured metadata, which we want higher than all unlisted metadata
        "concurrency",
        "env_vars",
        "job",
        "process",
        "psutils",
        "repos",

        # All other top level keys get sorted alphabetically at the bottom
    ]

    # Define key orders for nested dictionaries
    # process_key_order = [
    #     "status_message",
    #     "args",
    #     "return_code",
    #     "execution_time_seconds",
    #     "execution_time",
    #     "success",
    #     "start_time",
    #     "end_time",
    #     "pid",
    #     "pgid",
    #     "output_line_count",
    #     "truncated_output"
    # ]

    # Rename 'event' to 'message'
    if "event" in event_dict:
        event_dict["message"] = event_dict.pop("event")

    # TODO: Ensure the ctx.job dict is logged, if present

    # Sort top level keys,
    # Also sorts (almost) all subdicts alphabetically
    event_dict = sort_dict_by_key_order(event_dict, top_level_key_order)

    # # Sort nested dictionaries
    # if "process" in event_dict and isinstance(event_dict["process"], dict):
    #     event_dict["process"] = sort_dict_by_key_order(event_dict["process"])

    # if "psutils" in event_dict and isinstance(event_dict["psutils"], dict):
    #     event_dict["psutils"] = sort_dict_by_key_order(event_dict["psutils"])

    return json.dumps(event_dict, default=str)


def sort_dict_by_key_order(input_dict: dict, key_order: list[str] = []):

    """
    Sort dictionary by preferred key order

    If no key order is provided, then just sort dict keys in alphabetical order

    Uses recursion to sort subdicts
    """

    output_dict = {}

    # Add keys in preferred order
    for key in key_order:
        if key in input_dict:
            output_dict[key] = input_dict.pop(key)

    # Add any remaining keys at the end, sorted alphabetically
    output_dict.update(
        dict(
            sorted(
                input_dict.items()
            )
        )
    )

    # If the dict has subdicts, then sort their keys too, by recursion
    for item in output_dict:
        if isinstance(output_dict[item], dict) and item not in ("concurrency", "code"):
            output_dict[item] = sort_dict_by_key_order(output_dict[item])

    return output_dict
