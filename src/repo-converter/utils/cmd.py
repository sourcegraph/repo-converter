#!/usr/bin/env python3
# Process management utilities

from utils.logging import log

from datetime import datetime, timedelta
import psutil
import subprocess

def run(command, cwd=None):
    """Run a shell command and return the output."""

    log(f"Running command: {str(command)}", "DEBUG")


def get_pid_uptime(pid:int = 1) -> timedelta | None:
    """Get the uptime of a process by PID."""

    pid_uptime = None

    try:

        pid_int                 = int(pid)
        pid_create_time         = psutil.Process(pid_int).create_time()
        pid_start_datetime      = datetime.fromtimestamp(pid_create_time)
        pid_uptime_timedelta    = datetime.now() - pid_start_datetime
        pid_uptime_seconds      = pid_uptime_timedelta.total_seconds()
        pid_uptime              = timedelta(seconds=pid_uptime_seconds)

    except psutil.NoSuchProcess:
        pass

    return pid_uptime