#!/usr/bin/env python3
# Custom logging function with structured logging support

# Import repo-converter modules
from utils import secret
from utils.context import Context

# Import Python standard modules
from datetime import datetime
import inspect
import time

# Import third party modules
import structlog


def log(
        ctx: Context,
        message: str,
        level_name: str = "DEBUG",
        structured_data: dict = None,
        correlation_id: str = None,
        log_env_vars: bool = False,
        log_concurrency_status: bool = False,
        ) -> None:
    """
    Enhanced logging function with structured data support.

    Args:
        ctx: Context object containing run information
        message: Log message string
        level_name: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        structured_data: Optional dictionary of structured fields to include
        correlation_id: Optional correlation ID for tracking related operations
    """

    # Normalize level name
    level_name = str(level_name).upper()
    if level_name not in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
        level_name = "DEBUG"

    # Get structlog logger
    logger = structlog.get_logger()

    # Build structured data payload
    structured_payload = _build_structured_payload(
        ctx,
        structured_data,
        correlation_id,
        log_env_vars,
        log_concurrency_status,
        )

    # Apply redaction to the entire payload
    redacted_payload = secret.redact(ctx, structured_payload)

    # Log using structlog's logging commands, where the command is the log level's name
    getattr(logger, level_name.lower())(message, **redacted_payload)


def _build_structured_payload(
        ctx: Context,
        structured_data: dict = {},
        correlation_id: str = None,
        log_env_vars: bool = False,
        log_concurrency_status: bool = False,
        ) -> dict:
    """Build the complete structured data payload for logging"""


    current_timestamp = time.time()
    now = datetime.fromtimestamp(current_timestamp)

    # Capture code location info
    code_location = _capture_code_location()

    # Base payload with grouped structure
    payload = {

        # Top-level core fields
        "cycle": ctx.cycle,
        "date": now.date().isoformat(),
        "time": now.time().isoformat(),
        "timestamp": "%.4f" % current_timestamp, # Round to 4 digits, keeping trailing 0s, if any

        # Code/build-related fields grouped
        "code": code_location,

        # Container-related fields grouped
        "container": {
            "uptime": _format_uptime(current_timestamp - ctx.start_timestamp),
            "start_datetime": ctx.start_datetime,
            "id": ctx.container_id
        },

        "image": {
            "build_tag": ctx.env_vars.get("BUILD_TAG_OR_COMMIT_FOR_LOGS", "unknown"),
            "build_date": ctx.env_vars.get("BUILD_DATE", "unknown")
        }

    }

    # If a correlation_id is passed to the log() function, then use it as a top-level key
    # Other correlation_ids can be logged under other subdicts, ex. job, process
    if correlation_id:
        payload["correlation_id"] = correlation_id

    # Add environment variables if instructed
    if log_env_vars:
        payload["env_vars"] = ctx.env_vars

    # Add concurrency status if instructed
    if log_concurrency_status:
        payload["concurrency"] = ctx.concurrency_manager.get_status(ctx)

    # Merge any additional structured data passed in as parameters
    if structured_data:
        payload.update(structured_data)

    # Merge any job data from the context
    if ctx.job:
        payload.update({"job": dict(ctx.job)})

    # Remove any null values
    payload = _remove_null_values(payload)

    return payload


def _capture_code_location(skip_frames: int = 3, parent_frames: int = 2) -> dict:
    """
    Automatically capture code location information

    Args:
        skip_frames: Number of stack frames to skip to reach the caller
        parent_frames: Number of parent frames to capture above the caller
    """

    code_location = {}

    try:

        frame = inspect.currentframe()

        for i in range(skip_frames):
            if frame.f_back:
                frame = frame.f_back

        code_location["caller"] = {
            "module": frame.f_globals.get("__name__", "unknown"),
            "function": frame.f_code.co_name,
            "file": frame.f_code.co_filename,
            "line": frame.f_lineno,
        }

        for i in range(parent_frames):

            if frame.f_back:
                frame = frame.f_back

                if frame.f_globals.get("__name__", "unknown") in ("__main__", "unknown") \
                    and frame.f_code.co_name in ("<module>") \
                    and "main.py" in frame.f_code.co_filename:

                    break

                code_location[f"parent_{i+1}"] = {
                    "module": frame.f_globals.get("__name__", "unknown"),
                    "function": frame.f_code.co_name,
                    "file": frame.f_code.co_filename,
                    "line": frame.f_lineno,
                }

    except (AttributeError, TypeError):
        pass

    finally:
        del frame

    return code_location


def _format_uptime(uptime_seconds: float) -> str:
    """Format uptime seconds into human-readable format: 2d 14h 35m 42s"""

    total_seconds = int(uptime_seconds)

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    # Build format string, omitting zero values except seconds
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")

    # Always include seconds (even if 0)
    parts.append(f"{seconds}s")

    return " ".join(parts)


def _remove_null_values(payload: dict) -> dict:
    """
    Recursive function to remove keys from payload where values are null, or empty strings,
    but keep values set to 0
    """

    if type(payload) is dict:

        return dict((key, _remove_null_values(value)) for key, value in payload.items() if value == 0 or (value is not None and value != "" and _remove_null_values(value)))

    elif type(payload) is list:

        return [_remove_null_values(value) for value in payload if value == 0 or (value is not None and value != "" and _remove_null_values(value))]

    else:
        return payload


def set_job_result(ctx: Context, action: str = None, reason: str = None, success: bool = None) -> None:
    """
    Set the result subdict for job logs
    """

    ctx.job["result"].update(
        {
            "action": action,
            "reason": reason,
            "success": success
        }
    )
