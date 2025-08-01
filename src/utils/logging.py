#!/usr/bin/env python3
# Custom logging function with structured logging support

# Import repo-converter modules
from utils import secret
from utils.context import Context

# Import Python standard modules
from datetime import datetime
import inspect
import os
import sys
import time
import traceback

# Import third party modules
import structlog


def log(
        ctx: Context,
        message: str,
        event_log_level_name: str = "DEBUG",
        structured_data: dict = None,
        correlation_id: str = "",
        log_env_vars: bool = False,
        log_concurrency_status: bool = False,
        exception = None
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
    event_log_level_name = str(event_log_level_name).upper()
    if event_log_level_name not in ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]:
        event_log_level_name = "DEBUG"

    # Get structlog logger
    logger = structlog.get_logger()

    # Build structured data payload
    structured_payload = _build_structured_payload(
        ctx,
        event_log_level_name,
        structured_data,
        correlation_id,
        log_env_vars,
        log_concurrency_status,
        exception
    )

    # Apply redaction to the entire payload
    redacted_payload = secret.redact(ctx, structured_payload)

    # Log using structlog's logging commands, where the command is the log level's name
    getattr(logger, event_log_level_name.lower())(message, **redacted_payload)

    # Exit the container for critical log events
    if "CRITICAL" in event_log_level_name:
        sys.exit(1)


def _build_structured_payload(
        ctx: Context,
        event_log_level_name: str,
        structured_data: dict = {},
        correlation_id: str = "",
        log_env_vars: bool = False,
        log_concurrency_status: bool = False,
        exception = None
    ) -> dict:
    """Build the complete structured data payload for logging"""


    current_timestamp = time.time()
    now = datetime.fromtimestamp(current_timestamp)

    # Base payload with grouped structure
    payload = {

        # Top-level core fields
        "cycle": ctx.cycle,
        "date": now.date().isoformat(),
        "time": now.time().isoformat(),

    }

    # Get stack
    code_location = _capture_code_location()

    # Ignore job context for some functions
    functions_to_ignore_ctx_job = [
        "status_monitor",
    ]
    ignore_ctx_job = False

    for function_to_ignore_ctx_job in functions_to_ignore_ctx_job:
        for caller in code_location:
            for value in code_location.get(caller).values():
                try:
                    if function_to_ignore_ctx_job in value:
                        ignore_ctx_job = True
                        break
                except TypeError:
                    pass

    if (
        ctx.env_vars.get("LOG_LEVEL") == "DEBUG" or
        event_log_level_name in ["CRITICAL", "ERROR", "WARNING"]
    ):

        pid = os.getpid()

        payload.update(
            {
                "pids" : {
                    "pid": pid,
                    "psid": os.getsid(pid),
                    "pgrp": os.getpgrp(),
                    "ppid": os.getppid(),
                },
                "code": code_location,
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
        )

    # Merge any job data from the context
    if ctx.job and not ignore_ctx_job:

        ctx_job_config  = ctx.job.get("config",{})
        repo_key        = ctx_job_config.get("repo_key", "")
        if repo_key:
            payload.update({"repo_key": repo_key})

        ctx_job_result  = ctx.job.get("result",{})
        start_timestamp = ctx_job_result.get("start_timestamp")
        end_timestamp   = ctx_job_result.get("end_timestamp")
        execution_time  = ctx_job_result.get("execution_time")

        # If the job is still running
        if start_timestamp and not end_timestamp and not execution_time:

            # Then add a running_time_seconds
            ctx.job["result"]["running_time_seconds"] = int(time.time() - start_timestamp)

        payload.update({"job": dict(ctx.job)})

    # Merge any additional structured data passed in as parameters
    if structured_data:
        payload.update(structured_data)

        # If job data was passed in via structured_data, then use it
        # Note: this could get confusing if overlapping
        # TODO: Is this still used?
        structured_data_job = structured_data.get("job",{})
        if structured_data_job:
            payload.update({"job": dict(structured_data_job)})

            structured_data_job_repo_key = structured_data_job.get("config",{}).get("repo_key")
            if structured_data_job_repo_key:
                payload.update({"repo_key": structured_data_job_repo_key})


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

    if exception:
        payload["exception"] = _get_exception_data(exception)

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


def _get_exception_data(exception) -> dict:
    """
    Parse attributes from the provided exception, and return them as a dict to be printed in structured logs
    """

    return_dict = {}

    if exception:

        return_dict["type"]         = type(exception)
        return_dict["args"]         = breakup_lists_and_strings(exception.args)

        traceback_original          = traceback.format_exception(exception)
        return_dict["traceback"]    = breakup_lists_and_strings(traceback_original)

    return return_dict


def breakup_lists_and_strings(input) -> list[str]:
    """
    Parse individual attributes from exceptions
    Take in either a string or a list of strings
    Break up strings with newlines
    Return a list of strings
    """

    return_list = []

    if isinstance(input, str):
        input = list([input])

    if isinstance(input, list):
        for line in input:
            return_list += line.splitlines()

    return return_list


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


def set_job_result(ctx: Context, action: str = "", reason: str = "", success: bool = None) -> None:
    """
    Set the result subdict for job logs
    """

    # Loop through the list of function args
    variables_and_values = [
        ("action", action),
        ("reason", reason),
        ("success", success),
    ]

    # Pop them out of the result dict
    for variable, value in variables_and_values:

        if ctx.job["result"].get(variable):
            ctx.job["result"].pop(variable)

        # If a value was passed in, then set it
        if value:
            ctx.job["result"].update({variable: value})
