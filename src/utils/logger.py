#!/usr/bin/env python3
# Configure logger, without importing Context module

# Try to use canonical log lines wherever possible, ex. at the end of each subprocess_run execution
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


def _custom_json_renderer(logger, method_name, event_dict):
    """
    Custom JSON renderer that:
    - Renames keys, ex. 'event' to 'message'
    - Sorts keys
    """

    # Define the desired key order
    ordered_keys = [
        "level",
        "message", 
        "run_count",
        "date",
        "time",
        "timestamp",
        "container",
        "code"
    ]

    # Rename 'event' to 'message'
    if "event" in event_dict:
        event_dict["message"] = event_dict.pop("event")

    # Create ordered dictionary starting with known keys
    ordered_dict = {}

    # Add keys in preferred order
    for key in ordered_keys:
        if key in event_dict:
            ordered_dict[key] = event_dict.pop(key)

    # Add any remaining keys at the end
    ordered_dict.update(event_dict)

    return json.dumps(ordered_dict, default=str)


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
