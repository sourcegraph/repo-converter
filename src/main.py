#!/usr/bin/env python3
# Entry point for the repo-converter container

# Import repo-converter modules
from config import load_env, load_repos, validate_env
from utils import cmd, concurrency, concurrency_monitor, convert_repos, git, logger, signal_handler
from utils.context import Context
from utils.log import log

# Import Python standard modules
import time


def main():
    """Main entry point for the repo-converter container"""

    ### Initialization

    # Load environment variables from the container's running environment into env_vars dict
    # Assuming the env vars can't be changed without restarting the container
    # Initialize context with env vars
    ctx = Context(
            load_env.load_env_vars()
        )

    # Configure logging
    logger.configure_logger(ctx.env_vars["LOG_LEVEL"])

    # Validate env vars, now that we have logging available
    validate_env.validate_env_vars(ctx)

    # Log the container start event
    log(ctx, f"Starting container; running as resuid {ctx.resuid}", "info", log_env_vars = True)

    # Register signal handlers for graceful shutdown
    signal_handler.register_signal_handler(ctx)

    # Create semaphores for concurrency limits
    # Store them back in the context object
    ctx.concurrency_manager = concurrency.ConcurrencyManager(ctx)

    # Start concurrency_monitor
    # TODO: Sort out if this is needed / duplicative,
    # and if needed, does it need to be in a separate thread?
    # And if it needs to be in a separate thread, how to kill it when the main thread dies
    # So that the container can die and get restarted
    concurrency_monitor.start_concurrency_monitor(ctx)

    # Extract the env vars used repeatedly, to keep this DRY
    # These values are only used in the main function
    interval = ctx.env_vars["REPO_CONVERTER_INTERVAL_SECONDS"]
    max_cycles = ctx.env_vars["MAX_CYCLES"]

    ### Application main loop
    while True:

        # Increment the run count
        ctx.cycle += 1

        # Log the start of the run
        log(ctx, f"Starting run", "info", log_env_vars = True)

        # Load the repos to convert from file, in case the file has been changed while the container is running
        load_repos.load_from_file(ctx)

        # Tidy up zombie processes from the previous run through this loop
        cmd.status_update_and_cleanup_zombie_processes(ctx)
        # This may be the right time to check which repos are still in progress, given running PIDs, still running from the previous run through this loop

        # Disable git safe directory, to work around "dubious ownership" errors
        git.git_global_config(ctx)

        # Run the main application logic
        convert_repos.start(ctx)
        # TODO: Add started repo conversion jobs to the context object?

        # Tidy up zombie processes which have already completed during this run through this loop
        cmd.status_update_and_cleanup_zombie_processes(ctx)
        # Run the same code again, to update the list of running repo conversion jobs in the context dict

        # Log the end of the run
        log(ctx, "Finishing run", "info")

        # Sleep the configured interval
        log(ctx, f"Sleeping main loop for REPO_CONVERTER_INTERVAL_SECONDS={interval} seconds", "info")
        time.sleep(interval)

        # If MAX_CYCLES was defined, and if we've reached it, then exit
        if max_cycles > 0 and ctx.cycle >= max_cycles:
            log(ctx, f"Reached MAX_CYCLES={max_cycles}, exiting loop"," warning")
            break

    # Log the exit event
    log(ctx, "Stopping container", "info", log_env_vars = True)


if __name__ == "__main__":
    main()
