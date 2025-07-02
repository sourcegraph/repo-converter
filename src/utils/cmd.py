#!/usr/bin/env python3
# Utility functions to execute external binaries, fork child processes, and track / cleanup child processes

# Import repo-converter modules
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


def calculate_subprocess_run_time(ctx: Context, return_dict) -> None:
    """
    Calculate the runtime of a subprocess and add it to the return dictionary.

    Args:
        ctx: Context object for logging
        return_dict: Dictionary containing start_time and optionally end_time

    Effects:
        Modifies return_dict by adding 'run_time' key with timedelta value
    """

    run_time = None

    if "start_time" in return_dict:

        if "end_time" in return_dict:

            run_time = return_dict["end_time"] - return_dict["start_time"]

        else:

            run_time = datetime.now() - return_dict["start_time"]

    else:

        log(ctx, f"return_dict is missing a start_time: {return_dict}", "debug")

    if run_time:

        return_dict["run_time"] = timedelta(seconds=run_time.total_seconds())


def get_pid_uptime(pid: int = 1) -> Optional[timedelta]:
    """
    Get the uptime of a process by PID.

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


def print_process_status(ctx: Context,
                        psutils_process_dict: Dict[str, Any] = {},
                        status_message: str = "",
                        args: Union[str, List[str]] = "",
                        std_out: str = "",
                        log_level: str = "debug") -> None:
    """
    Log detailed process status information including PID, runtime, and process metadata.

    Args:
        ctx: Context object for logging
        psutils_process_dict: Dictionary of process attributes from psutil
        status_message: Human-readable status description
        args: Command arguments that started the process
        std_out: Standard output from the process
        log_level: Log level for the output message

    Effects:
        Logs process status information via the logging system
    """

    # log(ctx, f"print_process_status: psutils_process_dict: {psutils_process_dict}", "debug")

    log_message = ""

    # Why not try and set it here then
    psutils_process_dict["args"] = args

    pid = psutils_process_dict['pid']

    try:

        # Formulate the log message
        log_message += f"pid {pid}; "

        if status_message == "started":

            log_message += f"started; "

        else:

            log_message += f"{status_message}; "

            # Calculate its running time
            pid_uptime = get_pid_uptime(pid)

            if pid_uptime:
                log_message += f"running for {pid_uptime}; "

        # Pick the interesting bits out of the connections list
        # net_connections is a list of "pconn"-type objects, (named tuples of tuples)
        # If no network connections are currently open for this process, then the list is empty
        # This requires root on macOS for psutils to get this list, so the list is always empty on macOS unless the container is running as root
        if "net_connections" in psutils_process_dict.keys():

            connections = psutils_process_dict["net_connections"]

            # log(ctx, f"net_connections: {connections}", "debug")

            if isinstance(connections, list):

                connections_count = len(psutils_process_dict["net_connections"])

                psutils_process_dict["net_connections_count"] = connections_count

                if connections_count > 0:

                    connections_string = ""

                    for connection in connections:

                        # raddr=addr(ip='93.186.135.91', port=80), status='ESTABLISHED'),
                        connections_string += ":".join(map(str,connection.raddr))
                        connections_string += ":"
                        connections_string += connection.status
                        connections_string += ", "

                    # Save to the dict, chopping off the trailing comma and space
                    psutils_process_dict["net_connections"] = connections_string[:-2]

        psutils_process_dict_to_log = {key: psutils_process_dict[key] for key in ctx.process_attributes_to_log if key in psutils_process_dict}
        log_message += f"psutils_process_dict: {psutils_process_dict_to_log}; "

        if std_out:
            log_message += f"std_out: {std_out}; "

    except psutil.NoSuchProcess:
        log_message = f"pid {pid}; finished on status check"

    log(ctx, log_message, log_level)


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

        process_to_wait_for     = None
        psutils_process_dict    = {}
        status_message          = ""

        try:

            # Create an instance of a Process object for the PID number
            # Raises psutil.NoSuchProcess if the PID has already finished
            process_to_wait_for = psutil.Process(process_pid_to_wait_for)

            # Get the process attributes from the OS
            psutils_process_dict = process_to_wait_for.as_dict(attrs=ctx.process_attributes_to_fetch)

            # This rarely fires, ex. if cleaning up processes at the beginning of a script execution and the process finished during the interval
            if process_to_wait_for.status() == psutil.STATUS_ZOMBIE:
                status_message = "is a zombie"

            # Wait a short period, and capture the return status
            # Raises psutil.TimeoutExpired if the process is busy executing longer than the wait time
            return_status = process_to_wait_for.wait(0.1)
            status_message = f"finished with return status: {str(return_status)}"

        except psutil.NoSuchProcess as exception:
            status_message = "finished on wait"

        except psutil.TimeoutExpired as exception:
            status_message = "still running"

        except Exception as exception:
            status_message = f"raised an exception while waiting: {type(exception)}, {exception.args}, {exception}"

        if "pid" not in psutils_process_dict.keys():
            psutils_process_dict["pid"] = process_pid_to_wait_for

        print_process_status(ctx = ctx, psutils_process_dict = psutils_process_dict, status_message = status_message)


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
    - Gather the needed command output and metadata
    - Handle generic process errors

    Args:
        ctx: Context object
        args: Command arguments as string or list
        password: Optional password for stdin
        echo_password: Whether to echo password
        quiet: Suppress non-error logging
        correlation_id: Optional correlation ID to link related operations
    """

    # Normalize args as a string for log output
    if isinstance(args, list):
        arg_string = " ".join(args)
    elif isinstance(args, str):
        arg_string = args

    # Use provided correlation ID or generate one for linking start/end events
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())[:8]

    # Log command start with structured data
    start_data = {
        "command": {
            "args": arg_string,
        }
    }
    log(ctx, f"Command starting", "info", start_data, correlation_id)

    # Which log level to emit log events at,
    # so events are only logged if this level his higher than the LOG_LEVEL the container is running at
    log_level                           = "debug"

    # Dict for psutils to fill with .as_dict() function, which is only useful inside this module's process logging
    psutils_process_dict                = {}

    # Add the args to ths psutils dict, for cmd module's logging, to show the user which subprocess this module was working on for these log events
    psutils_process_dict["args"]        = args

    # Dict of only the useful bits to return back to the calling function, for the calling function to consume
    return_dict                         = {}
    return_dict["args"]                 = args
    return_dict["output"]               = None
    return_dict["returncode"]           = 1
    return_dict["start_time"]           = datetime.now()

    # Set empty variables to prevent access before defined errors
    status_message                      = ""
    subprocess_output                   = ""
    truncated_subprocess_output_to_log  = None

    try:

        # Create the process object and start it
        subprocess_to_run = psutil.Popen(
            args        = args,
            preexec_fn  = os.setsid, # Create new process group for better cleanup
            stderr      = subprocess.STDOUT,
            stdin       = subprocess.PIPE,
            stdout      = subprocess.PIPE,
            text        = True,
        )

        try:

            # Immediately capture basic process info before it can finish, or SIGCHLD can reap it
            basic_process_info = {
                "pid": subprocess_to_run.pid,
            }

            # Try to get full process attributes from the OS
            # The .as_dict() function can take longer to run than some subprocesses,
            # so it may fail, trying to read metadata for procs which no longer exist in the OS
            # I really wish psutils had a way around this, to gather the data as it's created in .Popen
            psutils_process_dict = subprocess_to_run.as_dict(attrs=ctx.process_attributes_to_fetch)
            psutils_process_dict["pgid"] = os.getpgid(psutils_process_dict["pid"])
            status_message = "started"

        except (psutil.NoSuchProcess, ProcessLookupError):
            # Process finished so quickly it was reaped before we could get detailed info

            # Merge in our basic info in case some fields are missing
            # This doesn't seem to work
            psutils_process_dict.update(basic_process_info)

            status_message = "Process finished before getting process metadata"
            if not quiet:
                log_level = "info"

        # It seems to be necessary to repeat this, as the dict may get cleared trying to assign it the value of .as_dict()
        psutils_process_dict["args"] = args

        # Log a starting message
        print_process_status(ctx = ctx, psutils_process_dict = psutils_process_dict, status_message = status_message, args = args, log_level = log_level)

        # If password is provided to this function, feed it into the subprocess' stdin pipe
        # communicate() also waits for the process to finish
        if echo_password:
            subprocess_output = subprocess_to_run.communicate(password)

        else:
            subprocess_output = subprocess_to_run.communicate()

        # Set the output to return
        subprocess_output = subprocess_output[0].splitlines()
        return_dict["output"] = subprocess_output

        # Set the output to log
        truncated_subprocess_output_to_log = truncate_subprocess_output(subprocess_output)

        # If the process exited successfully
        if subprocess_to_run.returncode == 0:

            status_message = f"succeeded"

            return_dict["returncode"] = 0

        else:

            status_message = "failed"

            if not quiet:
                log_level = "error"

    # Catching the CalledProcessError exception,
    # only to catch in case that the subprocess' proc _itself_ raised an exception
    # not necessarily any below processes the subprocess created
    except subprocess.CalledProcessError as exception:

        status_message = f"raised an exception: {type(exception)}, {exception.args}, {exception}"
        if not quiet:
            log_level = "error"

    # If the process ran so quickly that the psutil object doesn't have time to grab the dict,
    # it raises a FileNotFoundError exception
    except FileNotFoundError as exception:

        # Use the basic process info we captured earlier
        psutils_process_dict = basic_process_info
        status_message = "Process finished before getting process metadata (FileNotFoundError)"
        if not quiet:
            log_level = "info"

    # If the command fails
    if subprocess_to_run.returncode != 0:

        # There's a high chance it was caused by one of the lock files
        # Only check lock files for git commands with sufficient arguments
        if "git" in arg_string and lock.check_lock_files(ctx, psutils_process_dict):

            # Change the log_level to debug so the failed process doesn't log an error in print_process_status()
            log_level = "debug"


    # Get end time and calculate run time
    return_dict["end_time"] = datetime.now()
    calculate_subprocess_run_time(ctx, return_dict)

    # Determine success/failure
    success = subprocess_to_run.returncode == 0
    success_status = "success" if success else "failure"

    # Calculate execution time in seconds
    execution_time_seconds = return_dict["run_time"].total_seconds() if "run_time" in return_dict else 0

    # Separate stdout and stderr (our current setup combines them)
    stdout_output = subprocess_output if isinstance(subprocess_output, list) else []
    stderr_output = []  # Currently we redirect stderr to stdout

    # Log command completion with structured data
    completion_data = {
        "command": {
            "args": arg_string,
            "exit_code": subprocess_to_run.returncode,
            "execution_time_seconds": round(execution_time_seconds, 3),
            "start_time": return_dict["start_time"].isoformat(),
            "end_time": return_dict["end_time"].isoformat(),
            "stdout_lines": len(stdout_output),
            "stderr_lines": len(stderr_output),
            "stdout_preview": str(truncated_subprocess_output_to_log)[:200] if truncated_subprocess_output_to_log else "",
            "pid": subprocess_to_run.pid
        }
    }

    # Choose appropriate log level
    completion_level = "info" if success else "error"
    if quiet and success:
        completion_level = "debug"

    log(ctx, f"Command finished", completion_level, completion_data, correlation_id)

    return return_dict


def truncate_subprocess_output(subprocess_output: List[str]) -> List[str]:
    """
    Truncate subprocess output to prevent excessively long log entries.

    Limits both the total number of lines and the length of individual lines
    to keep log output manageable while preserving the most recent output.

    Args:
        subprocess_output: List of output lines from subprocess

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

    if len(str(subprocess_output)) > max_output_total_characters:

        subprocess_output_lines = len(subprocess_output)

        # If the output list is longer than max_output_lines lines, truncate it
        subprocess_output = subprocess_output[-max_output_lines:]
        subprocess_output.append(f"...LOG OUTPUT TRUNCATED FROM {subprocess_output_lines} LINES TO {max_output_lines} LINES")

        # Truncate really long lines
        for i in range(len(subprocess_output)):

            if len(subprocess_output[i]) > max_output_line_characters:
                subprocess_output_line_length = len(subprocess_output[i])
                subprocess_output[i] = textwrap.shorten(subprocess_output[i], width=max_output_line_characters, placeholder=f"...LOG LINE TRUNCATED FROM {subprocess_output_line_length} CHARACTERS TO {max_output_line_characters} CHARACTERS")

    return subprocess_output
