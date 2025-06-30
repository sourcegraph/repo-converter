#!/usr/bin/env python3
# Utility functions to execute external binaries, fork child processes, and track / cleanup child processes

# Import repo-converter modules
from utils.log import log
from utils.context import Context
from utils import lock

# Import Python standard modules
from datetime import datetime, timedelta
import os
import signal
import subprocess
import textwrap

# Import third party modules
import psutil


def get_pid_uptime(pid:int = 1) -> timedelta | None:
    """Get the uptime of a process by PID."""

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


def subprocess_run(ctx: Context, args, password=None, echo_password=None, quiet=False):

    # Which log level to emit log events at,
    # so events are only logged if this level his higher than the LOG_LEVEL the container is running at
    log_level                           = "debug"

    process_dict                        = {}
    process_dict["args"]                = args
    return_dict                         = {}
    return_dict["args"]                 = args
    return_dict["output"]               = None
    return_dict["returncode"]           = 1
    return_dict["start_time"]           = datetime.now()
    status_message                      = ""
    subprocess_output                   = ""
    truncated_subprocess_output_to_log  = None

    try:

        # Create the process object and start it
        subprocess_to_run = psutil.Popen(
            args        = args,
            preexec_fn  = os.setsid,  # Create new process group for better cleanup
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
            process_dict = subprocess_to_run.as_dict()
            status_message = "started"

        except psutil.NoSuchProcess:
            # Process finished so quickly it was reaped before we could get detailed info

            # Merge in our basic info in case some fields are missing
            process_dict.update(basic_process_info)
            status_message = "finished before getting the psutil.dict"
            if not quiet:
                log_level = "error"

        # Log a starting message
        print_process_status(ctx, process_dict, status_message)

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

            # TODO: Find a way to include the run time (wall time) in this output
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

        status_message = "finished before getting the psutil.dict"
        if not quiet:
            log_level = "error"

    # If the command fails
    if subprocess_to_run.returncode != 0:

        # There's a high chance it was caused by one of the lock files
        # If check_lock_files successfully cleared a lock file,
        if lock.check_lock_files(ctx, args, process_dict):

            # Change the log_level to debug so the failed process doesn't log an error in print_process_status()
            log_level = "debug"

    print_process_status(ctx, process_dict, status_message, str(truncated_subprocess_output_to_log), log_level)

    return_dict["end_time"] = datetime.now()
    get_subprocess_run_time(ctx, return_dict)

    return return_dict


def truncate_subprocess_output(subprocess_output):

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


def print_process_status(ctx: Context, process_dict = {}, status_message = "", std_out = "", log_level = "debug"):

    log_message = ""

    process_attributes_to_log = [
        "ppid",
        "name",
        "cmdline",
        "status",
        "num_fds",
        "cpu_times",
        "memory_percent",
        "connections_count",
        "connections",
        "open_files",
        "start_time",
        "end_time",
        "run_time",
    ]

    pid = process_dict['pid']

    try:

        # Formulate the log message
        log_message += f"pid {pid}; "

        if status_message == "started":

            log_message += f"started;   "

        else:

            log_message += f"{status_message}; "

            # Calculate its running time
            pid_uptime = get_pid_uptime(pid)

            if pid_uptime:
                log_message += f"running for {pid_uptime}; "

        # Pick the interesting bits out of the connections list
        # connections is usually in the dict, as a zero-length list of "pconn"-type objects, (named tuples of tuples)
        if "connections" in process_dict.keys():

            connections = process_dict["connections"]

            if isinstance(connections, list):

                process_dict["connections_count"] = len(process_dict["connections"])

                connections_string = ""

                for connection in connections:

                    # raddr=addr(ip='93.186.135.91', port=80), status='ESTABLISHED'),
                    connections_string += ":".join(map(str,connection.raddr))
                    connections_string += ":"
                    connections_string += connection.status
                    connections_string += ", "

                process_dict["connections"] = connections_string[:-2]

        process_dict_to_log = {key: process_dict[key] for key in process_attributes_to_log if key in process_dict}
        log_message += f"process_dict: {process_dict_to_log}; "

        if std_out:
            log_message += f"std_out: {std_out}; "

    except psutil.NoSuchProcess:
        log_message = f"pid {pid}; finished on status check"

    log(ctx, log_message, log_level)


def get_subprocess_run_time(ctx: Context, process_dict) -> None:

    run_time = None

    if "start_time" in process_dict:

        if "end_time" in process_dict:

            run_time = process_dict["end_time"] - process_dict["start_time"]

        else:

            run_time = datetime.now() - process_dict["start_time"]

    else:

        log(ctx, f"process_dict is missing a start_time: {process_dict}", "debug")

    if run_time:

        process_dict["run_time"] = timedelta(seconds=run_time.total_seconds())


def status_update_and_cleanup_zombie_processes(ctx: Context) -> None:

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

        process_dict        = {}
        process_to_wait_for = None
        status_message      = ""

        try:

            # Create an instance of a Process object for the PID number
            # Raises psutil.NoSuchProcess if the PID has already finished
            process_to_wait_for = psutil.Process(process_pid_to_wait_for)

            # Get the process attributes from the OS
            process_dict = process_to_wait_for.as_dict()

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

        if "pid" not in process_dict.keys():
            process_dict["pid"] = process_pid_to_wait_for

        print_process_status(ctx, process_dict, status_message)


# Signal handling
def register_signal_handler(ctx: Context):

    try:

        log(ctx, f"Registering signal handlers","debug")

        signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(ctx, sig, frame))
        signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(ctx, sig, frame))
        signal.signal(signal.SIGCHLD, lambda sig, frame: sigchld_handler(ctx, sig, frame))

    except Exception as exception:

        log(ctx, f"Registering signal handler failed with exception: {type(exception)}, {exception.args}, {exception}","error")


def signal_handler(ctx: Context, incoming_signal, frame):

    signal_name = signal.Signals(incoming_signal).name

    log(ctx, f"Received signal {signal_name} ({incoming_signal}), initiating graceful shutdown", "warning")

    # Kill all child processes in our process group
    try:

        # Send SIGTERM to all processes in our group
        os.killpg(os.getpgid(os.getpid()), signal.SIGTERM)
        log(ctx, "Sent SIGTERM to process group", "info")

    except ProcessLookupError:
        log(ctx, "No process group to terminate", "debug")

    except OSError as e:
        log(ctx, f"Error terminating process group: {e}", "error")

    # Clean up any remaining zombie processes
    status_update_and_cleanup_zombie_processes(ctx)

    # Exit gracefully
    log(ctx, f"Graceful shutdown complete for signal {signal_name}", "warning")
    exit(0)


def sigchld_handler(ctx: Context, incoming_signal, frame):
    """Handle SIGCHLD to immediately reap zombie children"""

    # Reap all available zombie children without blocking
    while True:

        try:

            # WNOHANG means don't block if no children are ready
            # -1 means wait for any child process
            pid, status = os.waitpid(-1, os.WNOHANG)

            # If pid is 0, no more children are ready
            if pid == 0:
                break

            # Log the reaped child
            log(ctx, f"SIGCHLD handler reaped child PID {pid} with status {status}", "debug")

        except OSError:
            # No child processes exist or other error
            break

        except Exception as e:
            log(ctx, f"Error in SIGCHLD handler: {e}", "debug")
            break
