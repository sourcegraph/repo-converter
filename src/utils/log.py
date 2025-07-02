#!/usr/bin/env python3
# Custom logging function with structured logging support

# Import repo-converter modules
from utils import secret
from utils.context import Context

# Import Python standard modules
from datetime import datetime
import inspect
import os
import time

# Import third party modules
import structlog


def log(ctx: Context, message: str, level_name: str = "DEBUG",
        structured_data: dict = None, correlation_id: str = None) -> None:
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
    structured_payload = _build_structured_payload(ctx, message, structured_data, correlation_id)

    # Apply redaction to the entire payload
    redacted_payload = secret.redact(ctx, structured_payload)

    # Log using structlog
    getattr(logger, level_name.lower())(message, **redacted_payload)


def _build_structured_payload(ctx: Context, message: str,
                              structured_data: dict = None, correlation_id: str = None) -> dict:
    """Build the complete structured data payload for logging"""

    now = datetime.now()

    current_timestamp = time.time()

    # Capture code location info
    code_location = _capture_code_location()

    # Base payload with grouped structure
    payload = {

        # Top-level core fields
        "cycle": ctx.cycle,
        "date": now.date().isoformat(),
        "time": now.time().isoformat(),
        "timestamp": round(current_timestamp,4),

        # Code/build-related fields grouped
        "code": {
            "module": code_location["module"],
            "function": code_location["function"],
            "file": code_location["file"],
            "line": code_location["line"],
            "build_tag": ctx.env_vars.get("BUILD_TAG_OR_COMMIT_FOR_LOGS", "unknown"),
            "build_date": ctx.env_vars.get("BUILD_DATE", "unknown")
        },

        # Container-related fields grouped
        "container": {
            "uptime": _format_uptime(current_timestamp - ctx.start_timestamp),
            "start_datetime": ctx.start_datetime,
            "id": ctx.container_id
        }

    }

    # Add correlation ID if provided
    if correlation_id:
        payload["correlation_id"] = correlation_id

    # Merge any additional structured data
    if structured_data:
        payload.update(structured_data)

    return payload


def _capture_code_location(skip_frames: int = 3) -> dict:
    """Automatically capture code location information"""

    try:

        frame = inspect.currentframe()

        for _ in range(skip_frames):
            if frame.f_back:
                frame = frame.f_back

        return {
            "module": frame.f_globals.get('__name__', 'unknown'),
            "function": frame.f_code.co_name,
            "file": frame.f_code.co_filename,
            "line": frame.f_lineno
        }

    except (AttributeError, TypeError):
        return {
            "module": "unknown",
            "function": "unknown",
            "file": "unknown",
            "line": 0
        }


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
