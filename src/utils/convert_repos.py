#!/usr/bin/env python3

# Main application logic to
# iterate through the repos_to_convert_dict,
# and spawn sub processes,
# based on parallelism limits per server

# This module uses different multiprocessing logic than cmd.py,
# because this module spawns new child processes targeting Python functions,
# whereas cmd.py spawns new child processes to call external binaries
# The zombie process cleanup routine in cmd.py should cleanup these processes as well

# Import repo-converter modules
from source_repo import svn
from utils.concurrency_manager import ConcurrencyManager
from utils.context import Context
from utils.log import log

# Import Python standard modules
import multiprocessing
import os
import uuid


def start(ctx: Context) -> None:
    """
    Main entry point between main module and repo conversion jobs, with concurrency management
    """

    # Reset the job dict, again, so it doesn't get passed on to other log events
    ctx.reset_job()

    # Log a start event
    # log(ctx, f"Starting convert_repos.start", "debug")

    # Loop through the repos_dict
    for repo_key in ctx.repos.keys():

        # Get repo's configuration dict
        repo_config = ctx.repos[repo_key]
        server_name = repo_config["max-concurrent-conversions-server-name"]
        # Find the repo type
        repo_type = repo_config.get("type", "").lower()

        # Generate a job ID, to link all events for each repo conversion job together in the logs
        job_trace = str(uuid.uuid4())[:8]

        # Set log context / structured data
        # Overwrite fresh for each job
        # Each conversion_wrapper child process gets its own copy of the context
        ctx.job.update(
            {
                "trace": job_trace,
                "config": {
                    "repo_key": repo_key,
                    "repo_type": repo_type,
                    "server_name": server_name,
                }
            }
        )

        # Log initial status
        log(ctx, f"{repo_key}; Starting repo conversion job", "debug")

        # Try to acquire concurrency slot
        # This will block and wait till a slot is available
        if not ctx.concurrency_manager.acquire_job_slot(ctx):
            log(ctx, f"{repo_key}; Could not acquire concurrency slot, skipping", "debug", log_concurrency_status=True)
            continue

        # Create a wrapper function that handles semaphore cleanup
        def conversion_wrapper(ctx):

            try:

                # TODO: Add other repo types as they are implemented
                if repo_type in ("svn", "subversion"):

                    # Start the conversion process
                    svn.convert(ctx)

            finally:

                # Always release the semaphore when done, regardless of success or fail
                ctx.concurrency_manager.release_job_slot(ctx)

                # log_concurrency_status=True causes an error inside this wrapper function
                log(ctx, f"{repo_key}; Finishing repo conversion job in pid={os.getpid()}", "info")

        # Start the process
        # Do not store any reference to the process, otherwise it may cling on as a zombie,
        # and we have enough other process checking / cleanup infra to handle these
        multiprocessing.Process(
            target=conversion_wrapper,
            name=f"convert_{repo_type}_{repo_key}",
            args=[ctx]
        ).start()

        # Reset the job dict, after it's been copied to the new process,
        # so it doesn't get passed on to other log events
        ctx.reset_job()


    # Reset the job dict, again, so it doesn't get passed on to other log events
    ctx.reset_job()

    # Log final status
    # log(ctx, f"Finishing convert_repos.start", "debug")
