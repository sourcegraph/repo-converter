#!/usr/bin/env python3
# Entry point for the repo-converter container

# Import repo-converter modules
from config import load_env, load_repos, validate_env
from utils import cmd, concurrency_manager, convert_repos, git, logger, signal_handler, status_monitor
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
    ctx.concurrency_manager = concurrency_manager.ConcurrencyManager(ctx)

    # Start status monitor
    status_monitor.start(ctx)

    # Extract the env vars used repeatedly, to keep this DRY
    # These values are only used in the main function
    interval = ctx.env_vars["REPO_CONVERTER_INTERVAL_SECONDS"]
    max_cycles = ctx.env_vars["MAX_CYCLES"]

    ### Application main loop
    while True:

        # Increment the run count
        ctx.cycle += 1

        # Log the start of the run
        log(ctx, f"Starting main loop run", "debug", log_env_vars = True)

        # Load the repos to convert from file, in case the file has been changed while the container is running
        load_repos.load_from_file(ctx)

        # Disable git safe directory, to work around "dubious ownership" errors
        git.git_global_config(ctx)

        # Run the main application logic
        convert_repos.start(ctx)

        # Sleep the configured interval
        log(ctx, f"Sleeping main loop for REPO_CONVERTER_INTERVAL_SECONDS={interval} seconds", "debug")
        time.sleep(interval)

        # If MAX_CYCLES was defined, and if we've reached it, then exit
        if max_cycles > 0 and ctx.cycle >= max_cycles:
            log(ctx, f"Reached MAX_CYCLES={max_cycles}, exiting main loop"," info")
            break

    # Set shutdown flag to stop background threads gracefully
    ctx.shutdown_flag = True

    # Log the exit event
    log(ctx, "Stopping container", "info", log_env_vars = True)


if __name__ == "__main__":
    main()
