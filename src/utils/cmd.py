#!/usr/bin/env python3
# Utility functions to execute external binaries, fork child processes, and track / cleanup child processes

# Import repo-converter modules
from email import message
from utils.log import log
from utils.context import Context
from utils import lock

# Import Python standard modules
from datetime import datetime, timedelta
from typing import Union, Optional, Dict, Any, List
import os
import subprocess
import textwrap
import uuid

# Import third party modules
import psutil # Check for breaking changes https://github.com/giampaolo/psutil/blob/master/HISTORY.rst


def get_pid_uptime(pid: int = 1) -> Optional[timedelta]:
    """
    Get the uptime of a running process by its PID.

    Called by other modules

    Args:
        pid: Process ID to check (defaults to PID 1)

    Returns:
        timedelta representing process uptime, or None if process doesn't exist
    """

    pid_uptime = None

    try:

        pid_create_time         = psutil.Process(pid).create_time()
        pid_start_datetime      = datetime.fromtimestamp(pid_create_time)
        pid_uptime_timedelta    = datetime.now() - pid_start_datetime
        pid_uptime_seconds      = pid_uptime_timedelta.total_seconds()
        pid_uptime              = timedelta(seconds=pid_uptime_seconds)

    except psutil.NoSuchProcess:
        return None

    return pid_uptime


def log_process_status(ctx: Context,
                        subprocess_psutils_dict: Dict[str, Any] = {},
                        subprocess_dict: Dict = {},
                        log_level: str = "",
                        ) -> None:


    """
    Log detailed process status information including PID, runtime, and process metadata.

    Called by subprocess_run and status_update_and_cleanup_zombie_processes

    For each piece of data I want to output, how do I pass it from subprocess_run into this function?

    Args:
        ctx: Context object for logging
        subprocess_psutils_dict: Dictionary of process attributes from psutil
        subprocess_dict: Dict of keys and values to log, which are not in the psutil dict
        log_level: Log level for the output message

    Effects:
        Logs process status information via the logging system
    """


    # log(ctx, f"log_process_status: subprocess_dict: {json.dumps(subprocess_dict, indent = 4, sort_keys=True, default=str)}; subprocess_psutils_dict: {json.dumps(subprocess_psutils_dict, indent = 4, sort_keys=True, default=str)}", "debug")

    # Take shallow copies of the dicts, so we can modify top level keys here to reduce duplicates in log output, without affecting the dict in the calling function; if we need to modify nested objects, then we'll need to switch to deep copies
    subprocess_dict_copy = subprocess_dict.copy()
    subprocess_psutils_dict_copy = subprocess_psutils_dict.copy()

    # Create output dicts to send to log() function
    structured_log_dict = {}
    subprocess_psutils_dict_to_log = {}

    # Set the log level for this event
    # Precedence:
        # function call parameter
        # subprocess_dict_copy["log_level"]
        # Default: debug
    if not log_level:
        log_level = subprocess_dict_copy.pop("log_level", "debug")

    # Gather the log message
    log_message = f"Process {subprocess_dict_copy.pop('status_message', 'status')}"

    # If there's a correlation_id, then pass it into the log function args
    correlation_id = subprocess_dict_copy.pop("correlation_id", None)

    # Remove the full output, to keep the truncated output
    subprocess_dict_copy.pop("output", "")

    # Try to get the running time if the pid is still running
    try:

        pid = None
        running_time = None

        if "pid" in subprocess_psutils_dict_copy.keys():
            pid = subprocess_psutils_dict_copy["pid"]
        elif "pid" in subprocess_dict_copy.keys():
            pid = subprocess_dict_copy["pid"]

        # Calculate its running time
        if pid:
            running_time = get_pid_uptime(pid)

        if running_time:
            subprocess_dict_copy["running_time"] = running_time

    except psutil.NoSuchProcess:
        log_message = "Process finished on status check"

    # Round memory_percent to 4 digits
    if "memory_percent" in subprocess_psutils_dict_copy.keys():
        subprocess_psutils_dict_copy["memory_percent"] = round(subprocess_psutils_dict_copy["memory_percent"],4)

    # Pick the interesting bits out of the connections list
    # net_connections is a list of "pconn"-type objects, (named tuples of tuples)
    # If no network connections are currently open for this process, then the list is empty
    # This requires root on macOS for psutils to get this list, so the list is always empty on macOS unless the container is running as root
    if "net_connections" in subprocess_psutils_dict_copy.keys():

        connections = subprocess_psutils_dict_copy["net_connections"]

        # log(ctx, f"net_connections: {connections}", "debug")

        if isinstance(connections, list):

            connections_count = len(subprocess_psutils_dict_copy["net_connections"])

            subprocess_psutils_dict_copy["net_connections_count"] = connections_count

            if connections_count > 0:

                connections_string = ""

                for connection in connections:

                    # raddr=addr(ip='1.2.3.4', port=80), status='ESTABLISHED'),
                    connections_string += ":".join(map(str,connection.raddr))
                    connections_string += ":"
                    connections_string += connection.status
                    connections_string += ", "

                # Save back to the dict, chopping off the trailing comma and space
                subprocess_psutils_dict_copy["net_connections"] = connections_string[:-2]

    # Truncate long lists of open files, ex. git svn fetch processes
    if "open_files" in subprocess_psutils_dict_copy.keys() and len(subprocess_psutils_dict_copy["open_files"]) > 0:
        subprocess_psutils_dict_copy["open_files"] = truncate_output(subprocess_psutils_dict_copy["open_files"])

    # Copy the remaining attributes to be logged
    subprocess_psutils_dict_to_log = {key: subprocess_psutils_dict_copy[key] for key in ctx.process_attributes_to_log if key in subprocess_psutils_dict_copy}

    # Copy the subprocess_psutils_dict_to_log dict as a sub dict in structured_log_dict, for organized output
    structured_log_dict["process"] = subprocess_dict_copy
    structured_log_dict["psutils"] = subprocess_psutils_dict_to_log

    # Log the event
    log(ctx, log_message, log_level, structured_log_dict, correlation_id)


def status_update_and_cleanup_zombie_processes(ctx: Context) -> None:
    """
    Find and clean up zombie child processes by waiting on them.

    This function identifies all child processes (direct and indirect descendants)
    of the current process and attempts to wait on them to clean up zombies.
    When running as PID 1 in a container, this prevents zombie accumulation.

    Args:
        ctx: Context object for logging

    Effects:
        - Waits on child processes to clean up zombies
        - Logs status information for each process found
    """

    # The current approach should return the same list of processes as just ps -ef when a Docker container runs this script as the CMD (pid 1)

    # Get the current process ID, should be 1 in Docker
    os_this_pid = os.getpid()

    # Using a set for built-in deduplication
    process_pids_to_wait_for = set()

    # Fill in the process_pids_to_wait_for set with all child / grandchild PIDs
    # Get a oneshot snapshot of all processes running this instant
    # Loop through for each processes
    for process in psutil.process_iter():

        # The process may finish in the time between .process_iter() and .parents()
        try:

            # Get all upstream parent PIDs of the process
            # Caught a process doesn't exist exception here, could see if it could be handled
            process_parents_pids = [process_parent.pid for process_parent in process.parents()]

            # If this pid is in the parents, then we know its a child / grandchild / great-grandchild / etc. process of this process
            if os_this_pid in process_parents_pids:

                # Add the process' own PID to the set
                process_pids_to_wait_for.add(process.pid)

                # Loop through the process' parents and add them to the set too
                for process_parents_pid in process_parents_pids:

                    process_pids_to_wait_for.add(process_parents_pid)

        except psutil.NoSuchProcess as exception:

            log(ctx, f"Caught an exception when listing parents of processes: {exception}", "debug")

    # Remove this script's PID so it's not waiting on itself
    process_pids_to_wait_for.discard(os_this_pid)

    # Now that we have a set of all child / grandchild / etc PIDs without our own
    # Loop through them and wait for each one
    # If the process is a zombie, then waiting for it:
        # Gets the return value
        # Removes the process from the OS' process table
        # Raises an exception
    for process_pid_to_wait_for in process_pids_to_wait_for:

        process_to_wait_for                 = None
        subprocess_psutils_dict             = {}
        subprocess_dict                     = {}
        subprocess_dict["status_message"]   = ""

        try:

            # Create an instance of a Process object for the PID number
            # Raises psutil.NoSuchProcess if the PID has already finished
            process_to_wait_for = psutil.Process(process_pid_to_wait_for)

            # Get the process attributes from the OS
            subprocess_psutils_dict = process_to_wait_for.as_dict(attrs=ctx.process_attributes_to_fetch)

            # This rarely fires, ex. if cleaning up processes at the beginning of a script execution and the process finished during the interval
            if process_to_wait_for.status() == psutil.STATUS_ZOMBIE:
                subprocess_dict["status_message"] = "is a zombie"

            # Wait a short period, and capture the return status
            # Raises psutil.TimeoutExpired if the process is busy executing longer than the wait time
            subprocess_dict["return_status"] = str(process_to_wait_for.wait(0.1))
            subprocess_dict["status_message"] = f"finished with return status: {subprocess_dict['return_status']}"

        except psutil.NoSuchProcess as exception:
            subprocess_dict["status_message"] = "finished on wait"

        except psutil.TimeoutExpired as exception:

            # Ignore logging main function processes which are still running
            if "cmdline" in subprocess_psutils_dict.keys() and subprocess_psutils_dict["cmdline"] == ["/usr/bin/python3", "/sourcegraph/repo-converter/src/main.py"]:
                continue

            # TODO: This is the log event that we're really looking for,
            # for long-running processes
            # How do we enrich these events, with process metadata in JSON keys?
            # repo
            # command
            # url
            # correlation_id

            subprocess_dict["status_message"] = "still running"

        except Exception as exception:
            subprocess_dict["status_message"] = f"raised an exception while waiting: {type(exception)}, {exception.args}, {exception}"

        if "pid" not in subprocess_psutils_dict.keys() and "pid" not in subprocess_dict.keys():
            subprocess_dict["pid"] = process_pid_to_wait_for

        log_process_status(ctx, subprocess_psutils_dict, subprocess_dict)


def subprocess_run(ctx: Context,
                  args: Union[str, List[str]],
                  password: Optional[str] = None,
                  echo_password: Optional[bool] = None,
                  quiet: bool = False,
                  correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Middleware function to
    - Take a CLI command as an args string or list of strings
    - Execute it as a subprocess
    - Wait for the subprocess to complete
    - Gather the needed command output and metadata
    - Handle generic process errors

    Args:
        ctx: Context object
        args: Command arguments as string or list
        password: Optional password for stdin
        echo_password: Whether to echo password
        quiet: Suppress non-error logging
        correlation_id: Optional correlation ID to link related operations

    Notes:
        Use log_process_status() in this function, to format and print process stats
    """

    # Dict for psutils to fill with .as_dict() function
    subprocess_psutils_dict            = {}

    # Dict for anything other functions need to consume,
    # which isn't set in subprocess_psutils_dict
    subprocess_dict                         = {}
    subprocess_dict["output"]               = None
    subprocess_dict["pid"]                  = None
    subprocess_dict["return_code"]          = None
    subprocess_dict["status_message"]       = "starting"
    subprocess_dict["success"]              = None
    subprocess_dict["truncated_output"]     = None

    # Normalize args as a string for log output
    if isinstance(args, list):
        subprocess_dict["command"] = " ".join(args)
    elif isinstance(args, str):
        subprocess_dict["command"] = args

    # If correlation ID is not provided, then generate one, to link start/end events in logs
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())[:8]
    subprocess_dict["correlation_id"] = correlation_id

    # Which log level to emit log events at,
    # so we can increase the log_level depending on process success / fail / quiet
    # so events are only logged if this level his higher than the LOG_LEVEL the container is running at
    subprocess_dict["log_level"] = "debug"

    # Log a starting message
    subprocess_dict["start_time"] = datetime.now()
    if not quiet:
        log_process_status(ctx, subprocess_psutils_dict, subprocess_dict)

    # Try to run the subprocess, and catch subprocess exceptions
    try:

        # Create the process object and start it
        sub_process = psutil.Popen(
            args        = args,
            preexec_fn  = os.setsid, # Create new process group for better cleanup
            stderr      = subprocess.STDOUT, # Redirect stderr to stdout for simplicity
            stdin       = subprocess.PIPE,
            stdout      = subprocess.PIPE,
            text        = True,
        )

        subprocess_dict["status_message"] = "started"

        # Try to read process metadata, and catch exceptions when the process finishes faster than its metadata can be read
        try:

            # Immediately capture basic process info,
            # in case the process exits faster than psutils can get the full .as_dict()
            # before it can finish, or SIGCHLD can reap it
            subprocess_dict["pid"] = sub_process.pid

            # Try to get full process attributes from the OS
            # The .as_dict() function can take longer to run than some subprocesses,
            # so it may fail, trying to read metadata for procs which no longer exist in the OS
            # I really wish psutils had a way around this, to gather the data as it's created in .Popen
            subprocess_psutils_dict = sub_process.as_dict(attrs=ctx.process_attributes_to_fetch)

            # psutil doesn't have a process group ID attribute, need to get it from the OS
            subprocess_dict["pgid"] = os.getpgid(subprocess_dict["pid"])

        # Process finished before we could get detailed info
        except (psutil.NoSuchProcess, ProcessLookupError, FileNotFoundError) as exception:

            subprocess_dict["status_message"] = "finished before getting process metadata"
            if not quiet:
                subprocess_dict["log_level"] = "info"

        # Log a started message
        # Either started, with psutil dict,
        # or finished before getting process metadata, with pid
        if not quiet:
            log_process_status(ctx, subprocess_psutils_dict, subprocess_dict)

        # If echo_password is provided to this function,
        # feed the password string into the subprocess' stdin pipe;
        # password could be an empty or arbitrary string as a workaround if a process needed it
        # communicate() also waits for the process to finish
        if echo_password:
            output = sub_process.communicate(password)
        else:
            output = sub_process.communicate()

        # Get the process' stdout and/or stderr
        # Have to do this inside the try / except block, in case the output isn't valid
        subprocess_dict["output"] = output[0].splitlines()

        # Truncate the output for logging
        subprocess_dict["truncated_output"] = truncate_output(subprocess_dict["output"])

        # If the process exited successfully, set the status_message now
        # Have to do this inside the try / except block, in case the sub_process object doesn't have a .returncode attribute
        subprocess_dict["return_code"] = sub_process.returncode
        if subprocess_dict["return_code"] == 0:

            subprocess_dict["status_message"] = "succeeded"
            subprocess_dict["success"] = True

        else:

            subprocess_dict["status_message"] = "failed"
            subprocess_dict["success"] = False
            if not quiet:
                subprocess_dict["log_level"] = "error"

    # Catching the CalledProcessError exception,
    # only to catch in case that the subprocess' sub_process _itself_ raised an exception
    # not necessarily any below processes the subprocess created
    except subprocess.CalledProcessError as exception:

        subprocess_dict["status_message"] = f"raised an exception: {type(exception)}, {exception.args}, {exception}"
        subprocess_dict["success"] = False
        if not quiet:
            subprocess_dict["log_level"] = "error"

    # Get end time and calculate run time
    subprocess_dict["end_time"] = datetime.now()
    subprocess_dict["execution_time"] = timedelta(seconds=(subprocess_dict["end_time"] - subprocess_dict["start_time"]).total_seconds())

    # If the command failed, check if it was due to a lock file being left behind by a previous execution dying
    if not subprocess_dict["success"]:

        # Only check lock files for git or svn commands
        if any(
            "git" in subprocess_dict["command"],
            "svn" in subprocess_dict["command"]
        ) and lock.clear_lock_files(ctx, subprocess_psutils_dict):

            # Change the log_level so the failed process doesn't log as an error
            subprocess_dict["log_level"] = "warning"
            subprocess_dict["status_message"] = "failed due to a lock file"

    if not (quiet and subprocess_dict["log_level"] == "debug"):
        log_process_status(ctx, subprocess_psutils_dict, subprocess_dict)

    return subprocess_dict


def truncate_output(output: List[str]) -> List[str]:
    """
    Truncate subprocess output to prevent excessively long log entries.

    Limits both the total number of lines and the length of individual lines
    to keep log output manageable while preserving the most recent output.

    Args:
        output: List of output lines from subprocess

    Returns:
        List of truncated output lines with truncation notices if applicable

    Note:
        Uses configurable limits for total characters, lines, and line length.
        Keeps the last N lines rather than the first N to preserve recent output.
    """

    # If the output is longer than max_output_total_characters, it's probably just a list of all files converted, so truncate it
    max_output_total_characters = 1000
    max_output_line_characters  = 200
    max_output_lines            = 10

    if len(str(output)) > max_output_total_characters:

        subprocess_output_lines = len(output)

        # If the output list is longer than max_output_lines lines, truncate it
        output = output[-max_output_lines:]
        output.append(f"...TRUNCATED FROM {subprocess_output_lines} LINES TO {max_output_lines} LINES FOR LOGGING")

        # Truncate really long lines
        for i in range(len(output)):

            if len(output[i]) > max_output_line_characters:
                subprocess_output_line_length = len(output[i])
                output[i] = textwrap.shorten(output[i], width=max_output_line_characters, placeholder=f"...LINE TRUNCATED FROM {subprocess_output_line_length} CHARACTERS TO {max_output_line_characters} CHARACTERS FOR LOGGING")

    return output
