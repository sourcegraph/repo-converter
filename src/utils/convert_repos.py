#!/usr/bin/env python3
# Main application logic to
# iterate through the repos_to_convert_dict,
# and spawn sub processes,
# based on parallelism limits per server

# Import repo-converter modules
from source_repo import svn
from utils.concurrency import ConcurrencyManager
from utils.context import Context
from utils.log import log

# Import Python standard modules
import multiprocessing


def start(ctx: Context, concurrency_manager: ConcurrencyManager) -> None:
    """Main entry point for repo conversion with concurrency management."""

    # Log initial status
    status = concurrency_manager.get_status()
    log(ctx, f"Starting convert_repos.start() with concurrency status: {status}", "info")

    # List to track started processes for cleanup
    # TODO: Store this in ctx, and add all child procs to it?
    active_processes = []

    # Loop through the repos_dict
    for repo_key in ctx.repos.keys():

        # # Log initial status
        # status = concurrency_manager.get_status()
        # log(ctx, f"{repo_key}; Starting repo conversion with concurrency status: {status}", "info")

        # Get repo configuration
        repo_config = ctx.repos[repo_key]

        # TODO: Move extract_server_host function to config/repos.py
        server_hostname = concurrency_manager.extract_server_host(repo_config)

        # Try to acquire concurrency slot
        # This will block and wait till a slot is available
        if not concurrency_manager.acquire_job_slot(repo_key, server_hostname):
            log(ctx, f"{repo_key}; Could not acquire concurrency slot, skipping", "info")
            continue

        # Find the repo type
        repo_type = repo_config.get("type", "").lower()

        # Start the conversion process with concurrency management
        if repo_type in ("svn", "subversion"):
            log(ctx, f"Starting repo type {repo_type}, name {repo_key}, server {server_hostname}")

            # Create a wrapper function that handles semaphore cleanup
            def conversion_wrapper(ctx, repo_key, server_hostname, concurrency_manager):
                try:
                    svn.clone_svn_repo(ctx, repo_key)
                finally:
                    # Always release the semaphore when done
                    concurrency_manager.release_job_slot(repo_key, server_hostname)

            # Start the process
            process = multiprocessing.Process(
                target=conversion_wrapper,
                name=f"clone_svn_repo_{repo_key}",
                args=(ctx, repo_key, server_hostname, concurrency_manager)
            )
            process.start()
            active_processes.append((process, repo_key, server_hostname))

    # Log final status
    final_status = concurrency_manager.get_status()
    log(ctx, f"Completed repo iteration with final status: {final_status}", "info")

    # Clean up any processes that may have failed to release their semaphores
    cleanup_stale_processes(ctx, active_processes, concurrency_manager)


def cleanup_stale_processes(ctx: Context, active_processes: list, concurrency_manager: ConcurrencyManager) -> None:
    """Clean up any stale processes and their semaphores."""

    for process, repo_key, server_hostname in active_processes:

        if not process.is_alive() and process.exitcode is not None:

            # Process is done but may not have cleaned up properly
            try:
                concurrency_manager.release_job_slot(repo_key, server_hostname)
                log(ctx, f"{repo_key}; Cleaned up stale process semaphore", "debug")

            except Exception as e:
                log(ctx, f"{repo_key}; Error during stale process cleanup: {e}", "error")
