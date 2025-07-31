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
from utils.logging import log

# Import Python standard modules
import multiprocessing
import os
import uuid


def start(ctx: Context) -> None:
    """
    Main entry point between main module and repo conversion jobs, with concurrency management
    """

    # Loop through the repos_dict
    for repo_key in ctx.repos.keys():

        # Reset the job so it doesn't get passed to other log events
        ctx.reset_job()

        # Get repo's configuration dict
        repo_config = ctx.repos[repo_key]
        server_name = repo_config["server_name"]
        repo_type   = repo_config.get("type", "").lower()

        # Generate a job ID, to link all events for each repo conversion job together in the logs
        job_trace   = str(uuid.uuid4())[:8]

        job = {
            "trace": job_trace,
            "config": {
                "repo_key": repo_key,
                "repo_type": repo_type,
                "server_name": server_name,
            }
        }

        log_job = {"job": job}

        # Try to acquire concurrency slot
        # This will block and wait till a slot is available
        if not ctx.concurrency_manager.acquire_job_slot(ctx, job):
            log(ctx, f"Could not acquire concurrency slot, skipping", "debug", log_job, log_concurrency_status=True)
            return

        # Create a wrapper function that handles semaphore cleanup
        def conversion_job(ctx: Context, job: dict) -> None:

            # Start a new process session for these child procs
            os.setsid()

            # Now save job dict to context, as it shouldn't interfere with the contexts of log events outside of this job
            ctx.job.update(job)

            # Log initial status
            log(ctx, f"Starting repo conversion job", "debug", log_job)

            try:

                # TODO: Add other repo types as they are implemented
                if repo_type in ("svn"):

                    # Start the conversion process
                    svn.convert(ctx)

                else:
                    log(ctx, f"Repo type not implemented: {repo_type}", "error", log_job)

            finally:

                # Always release the semaphore when done, regardless of success or fail
                ctx.concurrency_manager.release_job_slot(ctx, job)

                # log_concurrency_status=True causes an error inside this wrapper function
                log(ctx, f"Finishing repo conversion job", "info")

        # Start the process
        # Do not store any reference to the process, otherwise it may cling on as a zombie,
        # and we have enough other process checking / cleanup infra to handle these
        multiprocessing.Process(
            target=conversion_job,
            name=f"convert_{repo_type}_{repo_key}",
            args=[ctx, job]
        ).start()

        # Reset the job so it doesn't get passed to other log events
        ctx.reset_job()
