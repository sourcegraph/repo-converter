#!/usr/bin/env python3

# Main application logic to
# iterate through the repos_to_convert_dict,
# and spawn sub processes,
# based on parallelism limits per server

# This module uses different multiprocessing logic than cmd.py,
# because this module spawns new child processes targeting Python functions,
# whereas cmd.py spawns new child processes to call external binaries

# Import repo-converter modules
from multiprocessing import process
from source_repo import svn
from utils.concurrency import ConcurrencyManager
from utils.context import Context
from utils.log import log

# Import Python standard modules
import multiprocessing
import os
import uuid


def start(ctx: Context) -> None:
    """
    Main entry point for repo conversion with concurrency management.
    """

    # Retrieve concurrency_manager from context
    concurrency_manager: ConcurrencyManager = ctx.concurrency_manager

    # Log a start event
    log(ctx, f"Starting convert_repos.start()", "info", log_concurrency_status=True)

    # Loop through the repos_dict
    for repo_key in ctx.repos.keys():

        # Get repo's configuration dict
        repo_config = ctx.repos[repo_key]
        server_name = repo_config["max-concurrent-conversions-server-name"]
        # Find the repo type
        repo_type = repo_config.get("type", "").lower()

        # Generate a correlation ID, to link all events for each repo conversion job together in the logs
        # Set log context / structured data
        ctx.repo_conversion_job_log_data = {
            "repo_conversion_job": {
                "id": str(uuid.uuid4())[:8],
                "repo": repo_key,
                "repo_type": repo_type,
                "server-name": server_name
            }
        }

        # Log initial status
        log(ctx, "Starting repo conversion job", "debug", ctx.repo_conversion_job_log_data, log_concurrency_status=True)

        # Try to acquire concurrency slot
        # This will block and wait till a slot is available
        if not concurrency_manager.acquire_job_slot(repo_key, server_name):
            log(ctx, "Could not acquire concurrency slot, skipping", "info", ctx.repo_conversion_job_log_data, log_concurrency_status=True)
            continue

        # Create a wrapper function that handles semaphore cleanup
        def conversion_wrapper(ctx, repo_key, server_name):

            concurrency_manager: ConcurrencyManager = ctx.concurrency_manager

            try:

                # TODO: Add other repo types as they are implemented
                if repo_type in ("svn", "subversion"):

                    # Start the conversion process
                    svn.clone_svn_repo(ctx, repo_key)

            finally:

                # Always release the semaphore when done, regardless of success or fail
                concurrency_manager.release_job_slot(repo_key, server_name)

                log(ctx, f"Finishing repo conversion job in pid={os.getpid()}", "debug", ctx.repo_conversion_job_log_data)

                # log_concurrency_status=True causes an error inside this wrapper function
                # log(ctx, "Finishing repo conversion job", "debug", ctx.repo_conversion_job_log_data, log_concurrency_status=True)

        # Start the process
        process = multiprocessing.Process(
            target=conversion_wrapper,
            name=f"clone_svn_repo_{repo_key}",
            args=(ctx, repo_key, server_name)
        )
        process.start()

        # Store in context for signal handler access and cleanup
        process_tuple = (process, repo_key, server_name)
        ctx.active_repo_conversion_processes.append(process_tuple)


    # Clean up any completed processes
    cleanup_completed_repo_conversion_processes(ctx)

    # Log final status
    log(ctx, f"Finishing convert_repos.start()", "info", ctx.repo_conversion_job_log_data, log_concurrency_status=True)


def cleanup_completed_repo_conversion_processes(ctx: Context) -> None:
    """
    Clean up any stale processes and their semaphores.
    """

    log(ctx, f"len(ctx.active_repo_conversion_processes): {len(ctx.active_repo_conversion_processes)}; ctx.active_repo_conversion_processes: {ctx.active_repo_conversion_processes}", "debug")

    # TODO: Implement this cleanup function
    pass
