#!/usr/bin/env python3

# Main application logic to
# iterate through the repos_to_convert_dict,
# and spawn sub processes,
# based on parallelism limits per server

# This module uses different multiprocessing logic than cmd.py,
# because this module spawns new child processes targeting Python functions,
# whereas cmd.py spawns new child processes to call external binaries

# Import repo-converter modules
from source_repo import svn
from utils.concurrency import ConcurrencyManager
from utils.context import Context
from utils.log import log

# Import Python standard modules
import multiprocessing


def start(ctx: Context) -> None:
    """
    Main entry point for repo conversion with concurrency management.
    """

    concurrency_manager: ConcurrencyManager = ctx.concurrency_manager

    # Log a start event
    log(ctx, f"Starting convert_repos.start()", "info", log_concurrency_status=True)

    # Loop through the repos_dict
    for repo_key in ctx.repos.keys():

        # Log initial status
        log(ctx, f"{repo_key}; Starting repo conversion", "debug", log_concurrency_status=True)

        # Get repo's configuration dict
        repo_config = ctx.repos[repo_key]
        max_concurrent_conversions_server_name = repo_config["max-concurrent-conversions-server-name"]

        # Try to acquire concurrency slot
        # This will block and wait till a slot is available
        if not concurrency_manager.acquire_job_slot(repo_key, max_concurrent_conversions_server_name):
            log(ctx, f"{repo_key}; Could not acquire concurrency slot, skipping", "info", log_concurrency_status=True)
            continue

        # Find the repo type
        repo_type = repo_config.get("type", "").lower()

        # TODO: Refactor this to be more generic for different repo types

        # Start the conversion process with concurrency management
        if repo_type in ("svn", "subversion"):

            log(ctx, f"Starting repo type {repo_type}, name {repo_key}, server {max_concurrent_conversions_server_name}")

            # Create a wrapper function that handles semaphore cleanup
            def conversion_wrapper(ctx, repo_key, max_concurrent_conversions_server_name, concurrency_manager):

                try:
                    svn.clone_svn_repo(ctx, repo_key)
                finally:
                    # Always release the semaphore when done
                    concurrency_manager.release_job_slot(repo_key, max_concurrent_conversions_server_name)

            # Start the process
            process = multiprocessing.Process(
                target=conversion_wrapper,
                name=f"clone_svn_repo_{repo_key}",
                args=(ctx, repo_key, max_concurrent_conversions_server_name, concurrency_manager)
            )
            process.start()

            # Store in context for signal handler access and cleanup
            process_tuple = (process, repo_key, max_concurrent_conversions_server_name)
            ctx.active_multiprocessing_jobs.append(process_tuple)

    # Log final status
    log(ctx, f"Finishing convert_repos.start()", "info", log_concurrency_status=True)

    # Clean up any processes that may have failed to release their semaphores
    cleanup_stale_processes(ctx, concurrency_manager)


def cleanup_stale_processes(ctx: Context, concurrency_manager: ConcurrencyManager, timeout: int = 30) -> None:
    """Clean up any stale processes and their semaphores."""

    for process, repo_key, max_concurrent_conversions_server_name in ctx.active_multiprocessing_jobs:

        try:

            # Only clean up processes that are done but may not have cleaned up properly
            if not process.is_alive() and process.exitcode is not None:

                # Process is done but may not have released its semaphore
                concurrency_manager.release_job_slot(repo_key, max_concurrent_conversions_server_name)
                log(ctx, f"{repo_key}; Cleaned up stale process semaphore", "debug")

        except Exception as e:
            log(ctx, f"{repo_key}; Error during stale process cleanup: {e}", "error")
