#!/usr/bin/env python3
# Try to clear the various lock files left behind by different processes

# Import repo-converter modules
from utils import cmd
from utils.context import Context
from utils.log import log

# Import Python standard modules
import os
import subprocess


def clear_lock_files(ctx: Context) -> bool:
    """
    Check for the most common lockfiles and try to remove them, when a repo clone job fails
    """

    # Get the local repo path
    repo_path = ctx.job.get("job", {}).get("local_repo_path","")

    return_value    = False

    list_of_command_and_lock_file_path_tuples = [
        ("git garbage collection"       , ".git/gc.pid"                                     ), # fatal: gc is already running on machine '75c377aedbaf' pid 3700 (use --force if not)
        ("git svn fetch git-svn"        , ".git/svn/refs/remotes/git-svn/index.lock"        ), # fatal: Unable to create '/sg/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/git-svn/index.lock': File exists.
        ("git svn fetch origin trunk"   , ".git/svn/refs/remotes/origin/trunk/index.lock"   ), # fatal: Unable to create '/sg/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/origin/trunk/index.lock': File exists
        ("svn config"                   , ".git/svn/.metadata.lock"                         ), # error: could not lock config file .git/svn/.metadata: File exists config svn-remote.svn.branches-maxRev 125551: command returned error: 255
    ]

    for command, lock_file in list_of_command_and_lock_file_path_tuples:

        lock_file_path = f"{repo_path}/{lock_file}"

        if os.path.exists(lock_file_path):

            try:

                lock_file_content = ""

                try:

                    with open(lock_file_path, "r") as lock_file_object:
                        lock_file_content = lock_file_object.read()

                except UnicodeDecodeError as exception:
                    lock_file_content = exception

                log(ctx, f"Process failed to start due to a lock file in the repo at {lock_file_path}, but no other process is running with {command} for this repo; deleting the lock file so it'll try again on the next run; lock file content: {lock_file_content}", "warning")

                cmd_rm_lock_file = ["rm", "-f", lock_file_path]
                cmd.run_subprocess(ctx, cmd_rm_lock_file, name="cmd_rm_lock_file")

                return_value = True

            except subprocess.CalledProcessError as exception:
                log(ctx, f"Failed to delete lock file at {lock_file_path} with exception: {type(exception)}, {exception.args}, {exception}", "error")

    return return_value
