# Import repo-converter modules
from utils.context import Context
from utils.log import log
from utils import cmd

# Import Python standard modules
import subprocess
import os

def check_lock_files(ctx: Context, args, process_dict):

    return_value                = False
    repo_path                   = args[2] # [ "git", "-C", local_repo_path, "gc" ]
    list_of_process_and_lock_file_path_tuples = [
        ("Git garbage collection"       , ".git/gc.pid"                                     ), # fatal: gc is already running on machine '75c377aedbaf' pid 3700 (use --force if not)
        ("svn config"                   , ".git/svn/.metadata.lock"                         ), # error: could not lock config file .git/svn/.metadata: File exists config svn-remote.svn.branches-maxRev 125551: command returned error: 255
        ("git svn fetch git-svn"        , ".git/svn/refs/remotes/git-svn/index.lock"        ), # fatal: Unable to create '/sourcegraph/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/git-svn/index.lock': File exists.
        ("git svn fetch origin trunk"   , ".git/svn/refs/remotes/origin/trunk/index.lock"   ), # fatal: Unable to create '/sourcegraph/src-serve-root/svn.apache.org/asf/xmlbeans/.git/svn/refs/remotes/origin/trunk/index.lock': File exists
    ]

    # TypeError: can only join an iterable
    try:
        process_command = " ".join(process_dict["cmdline"])
    except TypeError as exception:
        process_command = process_dict["cmdline"]

    pid             = process_dict["pid"]

    for lock_file in list_of_process_and_lock_file_path_tuples:

        process = lock_file[0]
        lock_file_path = f"{repo_path}/{lock_file[1]}"

        if os.path.exists(lock_file_path):

            try:

                lock_file_content = ""

                try:

                    with open(lock_file_path, "r") as lock_file_object:
                        lock_file_content = lock_file_object.read()

                except UnicodeDecodeError as exception:
                    lock_file_content = exception

                log(ctx, f"pid {pid} failed; {process} failed to start due to finding a lock file in the repo at {lock_file_path}, but no other process is running with {process_command}; deleting the lock file so it'll try again on the next run; lock file content: {lock_file_content}", "warning")

                cmd_rm_lock_file = ["rm", "-f", lock_file_path]
                cmd.subprocess_run(ctx, cmd_rm_lock_file)

                return_value = True

            except subprocess.CalledProcessError as exception:
                log(ctx, f"Failed to rm -f lock file at {lock_file_path} with exception: {type(exception)}, {exception.args}, {exception}", "error")

    return return_value
