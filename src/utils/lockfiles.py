#!/usr/bin/env python3
# Try to clear the various lock files left behind by different processes
# TODO: Move to git module

# Import repo-converter modules
from utils import cmd
from utils.context import Context
from utils.logging import log

# Import Python standard modules
import os
import subprocess


def clear_lock_files(ctx: Context) -> bool:
    """
    Check for the most common lockfiles and try to remove them, when a repo clone job fails
    """

    # Get the local repo path
    local_repo_path = ctx.job.get("config", {}).get("local_repo_path","")

    # Use a set for found_lock_files, for deduplication in case the find command finds an existing lock file
    found_lock_files    = set()
    local_repo_path     += "/.git"
    lock_file_deleted   = False
    command             = "git svn fetch"

    # Check if known frequent lock files
    list_of_command_and_lock_file_path_tuples = [
        ("git garbage collection"       , "gc.pid"                                     ), # fatal: gc is already running on machine '75c377aedbaf' pid 3700 (use --force if not)
        ("git svn fetch git-svn"        , "svn/refs/remotes/git-svn/index.lock"        ), # fatal: Unable to create '/sg/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/git-svn/index.lock': File exists.
        ("git svn fetch origin trunk"   , "svn/refs/remotes/origin/trunk/index.lock"   ), # fatal: Unable to create '/sg/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/origin/trunk/index.lock': File exists
        ("svn config"                   , "svn/.metadata.lock"                         ), # error: could not lock config file .git/svn/.metadata: File exists config svn-remote.svn.branches-maxRev 125551: command returned error: 255
    ]

    # Check if known frequent lock files exist
    for command, lock_file in list_of_command_and_lock_file_path_tuples:

        lock_file_path = f"{local_repo_path}/{lock_file}"
        if os.path.exists(lock_file_path):
            found_lock_files.add(lock_file_path)


    # Search for any other lock files
    files_to_search_for  = [
        "index.lock"
    ]

    for file_to_search_for in files_to_search_for:

        # Run the search
        for root, dirs, files in os.walk(local_repo_path):
            if file_to_search_for in files:
                found_lock_files.add(os.path.join(root, file_to_search_for ))


    for found_lock_file in found_lock_files:

        try:

            lock_file_content = ""

            try:

                with open(found_lock_file, "r") as lock_file_object:
                    lock_file_content = lock_file_object.read()

            except UnicodeDecodeError as e:
                lock_file_content = e

            log(ctx, f"Process failed to start due to a lock file in the repo at {found_lock_file}, but no other process is running with {command} for this repo; deleting the lock file so it'll try again on the next run; lock file content: {lock_file_content}", "warning")

            cmd_rm_lock_file = ["rm", "-f", found_lock_file]
            cmd.run_subprocess(ctx, cmd_rm_lock_file, quiet=True, name="cmd_rm_lock_file")

            lock_file_deleted = True

        except subprocess.CalledProcessError as e:
            log(ctx, f"Failed to delete lock file at {found_lock_file} with exception", "error", exception=e)

        except FileNotFoundError:
            log(ctx, f"Lock file found at {found_lock_file}, but didn't exist at the time of deletion", "error")

    return lock_file_deleted
