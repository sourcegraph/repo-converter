#!/usr/bin/env python3
# Entry point for the repo-converter container

# Import repo-converter modules
from config import load_env, load_repos, validate_env
from utils import cmd, concurrency, concurrency_monitor, convert_repos, git, logger
from utils.context import Context
from utils.log import log

# Import Python standard modules
import time


def main():
    """Main entry point for the repo-converter container"""

    ### Initialization steps

    # Load environment variables from the container's running environment into env_vars dict
    # Assuming the env vars can't be changed without restarting the container
    env_vars = load_env.load_env_vars()

    # Create initial context from env vars
    ctx = Context(env_vars)

    # Configure logging
    logger.configure_logger(ctx.env_vars["LOG_LEVEL"])

    # Validate env vars, now that we have logging available
    validate_env.validate_env_vars(ctx)

    # DRY run log string
    run_log_string = ctx.get_run_log_string()

    # Log the container start event
    log(ctx, f"Starting container; {run_log_string}", "INFO")

    # Register signal handlers for graceful shutdown
    cmd.register_signal_handler(ctx)

    # Create semaphores for concurrency limits
    concurrency_manager = concurrency.ConcurrencyManager(ctx)

    # Start concurrency_monitor
    # TODO: Sort out if this is needed / duplicative,
    # and if needed, does it need to be in a separate thread?
    # And if it needs to be in a separate thread, how to kill it when the main thread dies
    # So that the container can die and get restarted
    concurrency_monitor.start_concurrency_monitor(ctx, concurrency_manager)

    # Extract the env vars used repeatedly, to keep this DRY
    # These values are only used in the main function
    interval = ctx.env_vars["REPO_CONVERTER_INTERVAL_SECONDS"]
    max_cycles = ctx.env_vars["MAX_CYCLES"]

    ### Application main loop
    while True:

        # Increment the run count
        ctx.run_count += 1

        # Log the start of the run
        uptime = cmd.get_pid_uptime()
        log(ctx, f"Starting run {ctx.run_count}; container uptime: {uptime}", "info")

        # Load the repos to convert from file, in case the file has been changed while the container is running
        load_repos.load_from_file(ctx)

        # Tidy up zombie processes from the previous run through this loop
        cmd.status_update_and_cleanup_zombie_processes(ctx)
        # This may be the right time to check which repos are still in progress, given running PIDs, still running from the previous run through this loop

        # Disable git safe directory, to work around "dubious ownership" errors
        git.git_global_config(ctx)

        # Run the main application logic
        convert_repos.start(ctx, concurrency_manager)
        # Add started repo conversion jobs to the context dict?

        # Tidy up zombie processes which have already completed during this run through this loop
        cmd.status_update_and_cleanup_zombie_processes(ctx)
        # Run the same code again, to update the list of running repo conversion jobs in the context dict

        # Log the end of the run
        uptime = cmd.get_pid_uptime()
        log(ctx, f"Finishing run {ctx.run_count}; container uptime: {uptime}", "info")

        # Sleep the configured interval
        log(ctx, f"Sleeping main loop for REPO_CONVERTER_INTERVAL_SECONDS={interval} seconds", "info")
        time.sleep(interval)

        # If MAX_CYCLES was defined, and if we've reached it, then exit
        if max_cycles > 0 and ctx.run_count >= max_cycles:
            log(ctx, f"Reached MAX_CYCLES={max_cycles}, exiting loop"," warning")
            break


    # Log the exit event
    uptime = cmd.get_pid_uptime()
    log(ctx, f"Stopping container; container uptime: {uptime}; {run_log_string}", "warning")

    # TODO: Wait till all child procs are finished before exiting
    # Exit the container
    # return

if __name__ == "__main__":
    main()
