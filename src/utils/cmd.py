#!/usr/bin/env python3
# Utility functions to execute external binaries, fork child processes, and track / cleanup child processes

# Import repo-converter modules
from utils.log import log
from utils.context import Context
from utils import lockfiles

# Import Python standard modules
from datetime import datetime, timedelta
from typing import Union, Optional, Dict, Any, List
import json
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


def _get_process_metadata(ctx: Context, process: psutil.Process) -> Dict:
    """
    Read and reformat the data returned by psutils.as_dict()
    """

    psutils_metrics_dict = {}

    # Get most of the process attributes from the OS
    try:
        psutils_metrics_dict = process.as_dict(attrs=ctx.psutils_process_attributes_to_fetch)
    except:
        #log(ctx, f"Failed to get psutils metrics for process {process}", "debug")
        pass

    # Get the named tuples as dicts
    try:
        psutils_metrics_dict["cpu_times"] = process.cpu_times()._asdict()
    except:
        #log(ctx, f"Failed to get cpu_times psutils metrics for process {process}", "debug")
        pass
    try:
        psutils_metrics_dict["create_datetime"] = datetime.fromtimestamp(psutils_metrics_dict["create_time"])
    except:
        #log(ctx, f"Failed to get create_datetime psutils metrics for process {process}", "debug")
        pass
    try:
        psutils_metrics_dict["io_counters"] = process.io_counters()._asdict()
    except:
        #log(ctx, f"Failed to get io_counters psutils metrics for process {process}", "debug")
        pass
    try:
        psutils_metrics_dict["memory_full_info"] = process.memory_full_info()._asdict()
    except:
        #log(ctx, f"Failed to get memory_full_info psutils metrics for process {process}", "debug")
        pass
    try:
        psutils_metrics_dict["open_files"] = list(open_file._asdict() for open_file in process.open_files())
    except:
        #log(ctx, f"Failed to get open_files psutils metrics for process {process}", "debug")
        pass
    try:
        psutils_metrics_dict["threads"] = list(thread._asdict() for thread in process.threads())
    except:
        #log(ctx, f"Failed to get threads psutils metrics for process {process}", "debug")
        pass

    return psutils_metrics_dict


def log_process_status(
        ctx: Context,
        subprocess_psutils_dict: Dict = {},
        subprocess_dict: Dict = {},
        log_level: str = "",
    ) -> None:
    """
    Log detailed process status information including PID, runtime, and process metadata.

    Called by run_subprocess and status_update_and_cleanup_zombie_processes

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
    subprocess_dict_input = subprocess_dict.copy()
    psutils_dict_input = subprocess_psutils_dict.copy()

    # Create output dicts to send to log() function
    structured_log_dict = {}
    psutils_dict_output = {}

    # Set the log level for this event
    # Precedence:
        # function call parameter
        # subprocess_dict_input["log_level"]
        # Default: debug
    if not log_level:
        log_level = subprocess_dict_input.pop("log_level", "debug")
    else:
        # If both are provided, discard the one in the dict, to avoid duplicate and / or contradicting outputs
        subprocess_dict_input.pop("log_level", "")

    # Gather the log message
    status_message = f"Process {subprocess_dict_input.pop('status_message', 'status')}"

    # Remove the full output, to keep the truncated output
    subprocess_dict_input.pop("output", "")

    # Try to get the running time if the pid is still running
    try:

        pid = None
        running_time = None

        if "pid" in psutils_dict_input.keys():
            pid = psutils_dict_input["pid"]
        elif "pid" in subprocess_dict_input.keys():
            pid = subprocess_dict_input["pid"]

        # Calculate its running time
        if pid:
            running_time = get_pid_uptime(pid)

        if running_time:
            subprocess_dict_input["running_time"] = running_time

    except psutil.NoSuchProcess:
        status_message = "Process finished"
        subprocess_dict_input["status_message_reason"] = "on status check"

    # Round memory_percent to 4 digits
    if "memory_percent" in psutils_dict_input.keys():
        psutils_dict_output["memory_percent"] = round(psutils_dict_input["memory_percent"],4)

    # Pick the interesting bits out of the connections list
    # net_connections is a list of "pconn"-type objects, (named tuples of tuples)
    # If no network connections are currently open for this process, then the list is empty
    # This requires root on macOS for psutils to get this list, so the list is always empty on macOS unless the container is running as root
    if "net_connections" in psutils_dict_input.keys():

        connections = psutils_dict_input["net_connections"]

        if isinstance(connections, list):

            connections_count = len(psutils_dict_input["net_connections"])

            psutils_dict_output["net_connections_count"] = connections_count

            if connections_count > 0:

                connections_list = []

                for connection in connections:

                    # raddr=addr(ip='1.2.3.4', port=80), status='ESTABLISHED'),

                    connections_string = ":".join(map(str,connection.raddr))
                    connections_string += f":{connection.status}"

                    connections_list.append(connections_string)

                # Save the list of connections back to the dict
                psutils_dict_input["net_connections"] = connections_list

    # Truncate long lists of open files, ex. git svn fetch processes
    if psutils_dict_input.get("open_files", ""):
        psutils_dict_output["open_files"] = truncate_output(ctx, psutils_dict_input["open_files"])

    # Copy the remaining attributes to be logged, without overwriting any already copied over
    for key in ctx.psutils_process_attributes_to_fetch:
        if key in psutils_dict_input and key not in psutils_dict_output:
            psutils_dict_output[key] = psutils_dict_input[key]

    # Copy the psutils_dict_output dict as a sub dict in structured_log_dict, for organized output
    structured_log_dict["process"] = subprocess_dict_input
    structured_log_dict["psutils"] = psutils_dict_output

    # Log the event
    log(ctx, status_message, log_level, structured_log_dict)


def run_subprocess(
        ctx:        Context,
        args:       Union[str, List[str]],
        password:   Optional[str]           = "",
        quiet:      Optional[bool]          = False,
        name:       Optional[str]           = "",
        stderr:     Optional[str]           = "stdout",
        expect:     Union[tuple[str,str], List[tuple[str,str]], None] = "",
    ) -> Dict[str, Any]:
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
        password: Password to be prefilled into stdin stream buffer
        quiet: Suppress non-error logging
        name: Optional command name to make logging events easier to find
        stderr:
            "stdout" (default), stderr stream is redirected to stdout stream
            "ignore", stderr stream is redirected to /dev/null
            "stderr", stderr stream is stored at return_dict["stderr"]
        expect:
            (prompt:str, response:str), if prompt is found in the stdout stream, then insert response into stdin stream

    Notes:
        Use log_process_status() in this function, to format and print process stats
    """

    # Dict for psutils to fill with .as_dict() function
    subprocess_psutils_dict            = {}

    # Dict for anything other functions need to consume,
    # which isn't set in subprocess_psutils_dict
    subprocess_dict                         = {}
    subprocess_dict["name"]                 = name          # For command logging
    subprocess_dict["output"]               = []            # For consumption by the calling function
    subprocess_dict["pid"]                  = None          # In case psutils doesn't get a pid in subprocess_psutils_dict
    subprocess_dict["return_code"]          = None          # Integer exit code
    subprocess_dict["status_message_reason"]= None          # Reason for process failure
    subprocess_dict["status_message"]       = "starting"    # starting / started / finished
    subprocess_dict["success"]              = None          # true / false; if false, the reason field should have a value
    subprocess_dict["truncated_output"]     = None          # For logging

    # Normalize args as a string for log output
    if isinstance(args, list):
        subprocess_dict["args"] = " ".join(args)
    elif isinstance(args, str):
        subprocess_dict["args"] = args

    # Generate a correlation ID for this subprocess run
    subprocess_span = str(uuid.uuid4())[:8]
    subprocess_dict["span"] = subprocess_span

    ## Handle stderr
    if "ignore" in stderr:
        stderr = subprocess.DEVNULL
    # If we want to separate it out into its own output
    elif "stderr" in stderr:
        stderr = subprocess.PIPE
    else:
        # Redirect stderr to stdout for simplicity
        stderr = subprocess.STDOUT

    ## Handle text vs byte mode
    # Byte mode is needed for stdout / stdin interaction
    # TODO: Handle all stdout as byte mode?
    text = True
    # if expect:
    #     text = True  # Keep text mode for SVN prompts

    # Which log level to emit log events at,
    # so we can increase the log_level depending on process success / fail / quiet
    # so events are only logged if this level his higher than the LOG_LEVEL the container is running at
    subprocess_dict["log_level"] = "debug"

    # Log a starting message
    subprocess_dict["start_time"] = datetime.now()
    # if not quiet:
    #     log_process_status(ctx, subprocess_psutils_dict, subprocess_dict)

    # Try to run the subprocess, and catch subprocess exceptions
    try:

        # Create the process object and start it
        # Do not raise an exception on process failure
        # TODO: Disable text = True, and handle stdin / out / err pipes as byte streams, so that stdout can be checked without waiting for a newline
        sub_process = psutil.Popen(
            args    = args,
            stderr  = stderr,
            stdin   = subprocess.PIPE,
            stdout  = subprocess.PIPE,
            text    = text,
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
            with sub_process.oneshot():

                subprocess_psutils_dict = _get_process_metadata(ctx, sub_process)

            # psutil doesn't have a process group ID attribute, need to get it from the OS
            subprocess_dict["pgid"] = os.getpgid(subprocess_dict["pid"])

        # Process finished before we could get detailed info
        except (psutil.NoSuchProcess, ProcessLookupError, FileNotFoundError) as exception:

            subprocess_dict["status_message"] = "finished"
            subprocess_dict["status_message_reason"] = "before getting process metadata"

            if not quiet:
                subprocess_dict["log_level"] = "info"

        # Log a started message
        # Either started, with psutil dict,
        # or finished before getting process metadata, with pid
        if not quiet:
            log_process_status(ctx, subprocess_psutils_dict, subprocess_dict)

        output = []

        # if expect:

        #     test_process = subprocess.Popen()
        #     test_process.poll()


        #     while not sub_process.poll():

        #         early_output = sub_process.stdout.readline()

        #         if early_output:

        #             output += early_output

        #             for prompt, response in expect:

        #                 if prompt in early_output:

        #                     sub_process.stdin.write(f"{response}\n")
        #                     sub_process.stdin.flush()
        #                     break

        if password:

            # If password is provided to this function,
            # feed the password string into the subprocess' stdin pipe;
            # password could be an empty or arbitrary string as a workaround if a process needed it
            # communicate() also waits for the process to finish
            output += sub_process.communicate(password)

        else:
            output += sub_process.communicate()


        # Get the process' stdout and/or stderr
        # Have to do this inside the try / except block, in case the output isn't valid
        subprocess_dict["output"] = output[0].splitlines()
        subprocess_dict["output_line_count"] = len(subprocess_dict["output"])
        # Truncate the output for logging
        subprocess_dict["truncated_output"] = truncate_output(ctx, subprocess_dict["output"])

        if "stderr" in stderr:
            subprocess_dict["stderr"] = output[1].splitlines()
            subprocess_dict["stderr_line_count"] = len(subprocess_dict["stderr"])
            subprocess_dict["truncated_stderr"] = truncate_output(ctx, subprocess_dict["stderr"])

        # If the process exited successfully, set the status_message now
        # Have to do this inside the try / except block, in case the sub_process object doesn't have a .returncode attribute
        subprocess_dict["return_code"] = sub_process.returncode

        if subprocess_dict["return_code"] == 0:

            subprocess_dict["status_message"] = "finished"
            subprocess_dict["status_message_reason"] = "succeeded"
            subprocess_dict["success"] = True

        else:

            subprocess_dict["status_message"] = "finished"
            subprocess_dict["status_message_reason"] = "failed"
            subprocess_dict["success"] = False
            if not quiet:
                subprocess_dict["log_level"] = "error"

    # Catching the CalledProcessError exception,
    # only to catch in case that the subprocess' sub_process _itself_ raised an exception
    # not necessarily any below processes the subprocess createdsubprocess_dict["command"]
    except subprocess.CalledProcessError as exception:

        subprocess_dict["status_message"] = "finished"
        subprocess_dict["status_message_reason"] = f"raised an exception: {type(exception)}, {exception.args}, {exception}"

        subprocess_dict["success"] = False
        if not quiet:
            subprocess_dict["log_level"] = "error"

    # Get end time and calculate run time
    subprocess_dict["end_time"] = datetime.now()
    execution_time_seconds = (subprocess_dict["end_time"] - subprocess_dict["start_time"]).total_seconds()
    subprocess_dict["execution_time_seconds"] = execution_time_seconds
    subprocess_dict["execution_time"] = timedelta(seconds=execution_time_seconds)

    # If the command failed, check if it was due to a lock file being left behind by a previous execution dying
    if not subprocess_dict["success"]:

        # Only check lock files for git or svn commands
        if any([
            "git" in subprocess_dict["args"],
            "svn" in subprocess_dict["args"]
        ]) and lockfiles.clear_lock_files(ctx):

            # Change the log_level so the failed process doesn't log as an error
            subprocess_dict["log_level"] = "warning"
            subprocess_dict["status_message"] = "finished"
            subprocess_dict["status_message_reason"] = "failed due to a lock file"

    if not (quiet and subprocess_dict["log_level"] == "debug"):
        log_process_status(ctx, subprocess_psutils_dict, subprocess_dict)

    return subprocess_dict


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
            with process_to_wait_for.oneshot():

                subprocess_psutils_dict = _get_process_metadata(ctx, process_to_wait_for)

                # This rarely fires, ex. if cleaning up processes at the beginning of a script execution and the process finished during the interval
                if process_to_wait_for.status() == psutil.STATUS_ZOMBIE:
                    subprocess_dict["status_message"] = "is a zombie"

            # Wait a short period, and capture the return status
            # Raises psutil.TimeoutExpired if the process is busy executing longer than the wait time
            subprocess_dict["return_status"] = str(process_to_wait_for.wait(0.1))
            subprocess_dict["status_message"] = "finished"
            subprocess_dict["status_message_reason"] = "on cleanup"

        except psutil.NoSuchProcess as exception:
            subprocess_dict["status_message"] = "finished"
            subprocess_dict["status_message_reason"] = "on wait"

        except psutil.TimeoutExpired as exception:

            # Ignore logging main function processes which are still running
            if "cmdline" in subprocess_psutils_dict.keys() and subprocess_psutils_dict["cmdline"] == ["/usr/bin/python3", "/sg/repo-converter/src/main.py"]:
                continue

            # TODO: This is the log event that we're really looking for,
            # for long-running processes
            # How do we enrich these events, with process metadata in JSON keys?
                # repo
                # command
                # url
                # process.id
                # latest line of stdout / stderr

            subprocess_dict["status_message"] = "still running"

            # Get latest output
            subprocess_dict["status_message_reason"] = f""

        except Exception as exception:
            subprocess_dict["status_message"] = "raised an exception while waiting"
            subprocess_dict["status_message_reason"] = f"{type(exception)}, {exception.args}, {exception}"

        if "pid" not in subprocess_psutils_dict.keys() and "pid" not in subprocess_dict.keys():
            subprocess_dict["pid"] = process_pid_to_wait_for

        log_process_status(ctx, subprocess_psutils_dict, subprocess_dict)


def truncate_output(ctx, output: List[str]) -> List[str]:
    """
    Truncate subprocess output to prevent excessively long log entries.

    Limits both the total number of lines and the length of individual lines
    to keep log output manageable while preserving the most recent output.

    If the output is longer than max_output_total_characters, it's probably just a list of all files converted, so truncate it

    Args:
        output: List of output lines from subprocess

    Returns:
        List of truncated output lines with truncation notices if applicable

    Note:
        Uses configurable limits for total characters, lines, and line length.
        Keeps the first and last max/2 lines
    """

    truncated_output: List[str] = []

    # Truncate the number of lines
    subprocess_output_lines     = len(output)
    truncated_output_max_lines  = ctx.env_vars["TRUNCATED_OUTPUT_MAX_LINES"]

    if subprocess_output_lines <= truncated_output_max_lines:

        # Remove any empty lines from the output
        truncated_output = [x for x in output if x]

    else:
        # Divide truncated_output_max_lines by 2, via integer division
        half_truncated_output_max_lines = truncated_output_max_lines // 2

        # head -n truncated_output_max_lines/2, ignoring empty lines
        first_half: List[str] = []
        for line in output:

            if line:
                first_half.append(line)

            if len(first_half) >= half_truncated_output_max_lines:
                break

        # tail -n truncated_output_max_lines/2, ignoring empty lines
        second_half: List[str] = []
        for line in reversed(output):

            if line:
                second_half.append(line)

            if len(second_half) >= half_truncated_output_max_lines:
                break

        # Add the first and second halves together, with truncated message in the middle
        truncated_output = [
            *first_half,
            f"...TRUNCATED FROM {subprocess_output_lines} LINES TO {truncated_output_max_lines} LINES FOR LOGS...",
            *reversed(second_half)
        ]

    # Truncate long lines
    truncated_output_max_line_length = ctx.env_vars["TRUNCATED_OUTPUT_MAX_LINE_LENGTH"]
    for i in range(len(truncated_output)):

        if len(truncated_output[i]) > truncated_output_max_line_length:

            subprocess_output_line_length = len(truncated_output[i])

            truncated_output[i] = textwrap.shorten(
                truncated_output[i],
                width=truncated_output_max_line_length,
                placeholder=f"...LINE TRUNCATED FROM {subprocess_output_line_length} CHARACTERS TO {truncated_output_max_line_length} CHARACTERS FOR LOGS"
            )

    return truncated_output
