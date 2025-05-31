#!/usr/bin/env python3
# Entry point for the repo-converter container

# Import repo-converter modules
from config import env, repos
from source_repo import convert_repos
from utils import cmd, git, logger
from utils.context import Context
from utils.logger import log

# Import Python standard modules
import time


def main() -> int:
    """Main entry point for the repo-converter container"""

    # Load environment variables from the container's running environment into env_vars dict
    # Assuming the env vars can't be changed without restarting the container
    env_vars = env.load_env_vars()

    # Create initial context from env vars
    ctx = Context(env_vars)

    # Configure logging
    logger.configure_logging(ctx)

    # DRY run log string
    run_log_string = ctx.get_run_log_string()

    # Log the container start event
    log(ctx, f"Starting container; {run_log_string}", "INFO")

    # Extract the env vars used repeatedly, to keep this DRY
    # These values are only used in the main function
    interval = ctx.env_vars['REPO_CONVERTER_INTERVAL_SECONDS']
    max_cycles = ctx.env_vars['MAX_CYCLES']

    # Application main loop
    while True:

        # Increment the run count
        ctx.run_count += 1

        # Log the start of the run
        uptime = cmd.get_pid_uptime()
        log(ctx, f"Starting run {ctx.run_count}; container uptime: {uptime}", "info")

        # Load the repos to convert from file, in case the file has been changed while the container is running
        repos.load_from_file(ctx)

        # Tidy up zombie processes from the previous run through this loop
        cmd.status_update_and_cleanup_zombie_processes(ctx)

        # Disable git safe directory, to work around "dubious ownership" errors
        git.git_config_safe_directory(ctx)

        # Run the main application logic
        convert_repos.start(ctx)

        # Tidy up zombie processes which have already completed during this run through this loop
        cmd.status_update_and_cleanup_zombie_processes(ctx)

        # Log the end of the run
        uptime = cmd.get_pid_uptime()
        log(ctx, f"Finishing run {ctx.run_count}; container uptime: {uptime}", "info")

        # Sleep the configured interval
        log(ctx, f"Sleeping main loop for REPO_CONVERTER_INTERVAL_SECONDS={interval} seconds", "info")
        time.sleep(interval)

        # If MAX_CYCLES was defined, and if we've reached it, then exit
        if max_cycles and ctx.run_count >= max_cycles:
            log(ctx, f"Reached MAX_CYCLES={max_cycles}, exiting loop"," warning")
            break


    # Log the exit event
    uptime = cmd.get_pid_uptime()
    log(ctx, f"Stopping container; container uptime: {uptime}; {run_log_string}", "warning")

    # Exit the container
    return 0

if __name__ == "__main__":
    main()
