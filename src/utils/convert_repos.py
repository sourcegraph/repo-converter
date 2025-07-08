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

                # Remove this repo from the active processes list
                ctx.active_repo_conversion_processes = [(process, repo, server_name) for process, repo, server_name in ctx.active_repo_conversion_processes if repo != repo_key]

                log(ctx, "Finishing repo conversion job", "debug", ctx.repo_conversion_job_log_data)

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

    # Log final status
    log(ctx, f"Finishing convert_repos.start()", "info", ctx.repo_conversion_job_log_data, log_concurrency_status=True)

    # Clean up any processes that may have failed to release their semaphores
    cleanup_completed_repo_conversion_processes(ctx)


def cleanup_completed_repo_conversion_processes(ctx: Context) -> None:
    """
    Clean up any stale processes and their semaphores.
    """

    # Retrieve concurrency_manager from context
    concurrency_manager: ConcurrencyManager = ctx.concurrency_manager

    log(ctx, f"ctx.active_repo_conversion_processes: {ctx.active_repo_conversion_processes}", "debug")

    process: multiprocessing.Process
    for process, repo_key, server_name in ctx.active_repo_conversion_processes:

        log(ctx, f"for process: {process}, repo_key: {repo_key}, server_name: {server_name}, process.is_alive(): {process.is_alive()}, process.exitcode: {process.exitcode}", "debug")

        try:

            log(ctx, f"if not process.is_alive() and process.exitcode is not None: {process.is_alive(), process.exitcode}", "debug")

            # Only clean up processes that are done but may not have cleaned up properly
            if not process.is_alive() and process.exitcode is not None:

                # Process is done but may not have released its semaphore
                concurrency_manager.release_job_slot(repo_key, server_name)

                # Remove this repo from the active processes list
                ctx.active_repo_conversion_processes = [(process, repo, server_name) for process, repo, server_name in ctx.active_repo_conversion_processes if repo != repo_key]

                log(ctx, f"{repo_key}; Cleaned up stale process semaphore", "debug")

        except Exception as e:
            log(ctx, f"{repo_key}; Error during stale process cleanup: {e}", "error")
