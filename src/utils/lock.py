#!/usr/bin/env python3
# Try to clear the various lock files left behind by different processes

# Import repo-converter modules
from utils import cmd
from utils.context import Context
from utils.log import log

# Import Python standard modules
import os
import subprocess


def clear_lock_files(ctx: Context, psutils_process_dict) -> bool:

    args                        = psutils_process_dict['args']
    repo_path                   = args[2] # [ "git", "-C", local_repo_path, "gc" ]
    return_value                = False
    list_of_command_and_lock_file_path_tuples = [
        ("git garbage collection"       , ".git/gc.pid"                                     ), # fatal: gc is already running on machine '75c377aedbaf' pid 3700 (use --force if not)
        ("git svn fetch git-svn"        , ".git/svn/refs/remotes/git-svn/index.lock"        ), # fatal: Unable to create '/sourcegraph/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/git-svn/index.lock': File exists.
        ("git svn fetch origin trunk"   , ".git/svn/refs/remotes/origin/trunk/index.lock"   ), # fatal: Unable to create '/sourcegraph/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/origin/trunk/index.lock': File exists
        ("svn config"                   , ".git/svn/.metadata.lock"                         ), # error: could not lock config file .git/svn/.metadata: File exists config svn-remote.svn.branches-maxRev 125551: command returned error: 255
    ]

    try:

        # If the cmdline is a list of strings
        psutils_process_command = " ".join(psutils_process_dict["cmdline"])

    except TypeError as exception:

        # If the cmdline is a single string
        # TypeError: can only join an iterable
        psutils_process_command = psutils_process_dict["cmdline"]

    except KeyError:

        # KeyError: 'cmdline'
        # psutils_process_dict doesn't have an attribute cmdline??
        # TODO: Review the calling code to see if this is a result of the recent concurrency work
        log(ctx, f"Failed to check for lock files for process; args: {args}; dict: {psutils_process_dict}", "error")
        return False

    pid = psutils_process_dict["pid"]

    for lock_file in list_of_command_and_lock_file_path_tuples:

        command = lock_file[0]
        lock_file_path = f"{repo_path}/{lock_file[1]}"

        if os.path.exists(lock_file_path):

            try:

                lock_file_content = ""

                try:

                    with open(lock_file_path, "r") as lock_file_object:
                        lock_file_content = lock_file_object.read()

                except UnicodeDecodeError as exception:
                    lock_file_content = exception

                log(ctx, f"pid {pid} failed; {command} failed to start due to finding a lock file in the repo at {lock_file_path}, but no other process is running with {psutils_process_command}; deleting the lock file so it'll try again on the next run; lock file content: {lock_file_content}", "warning")

                cmd_rm_lock_file = ["rm", "-f", lock_file_path]
                cmd.run_subprocess(ctx, cmd_rm_lock_file)

                return_value = True

            except subprocess.CalledProcessError as exception:
                log(ctx, f"Failed to rm -f lock file at {lock_file_path} with exception: {type(exception)}, {exception.args}, {exception}", "error")

    return return_value
