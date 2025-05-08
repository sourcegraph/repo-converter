#!/usr/bin/env python3
# Entry point for the repo-converter container

# Import repo-converter modules
from config.git_global_config import git_config_safe_directory
from config.repos_to_convert_file import parse_repos_to_convert_file
from utils.logging import log
import config.env as env
import utils.logging
import utils.cmd as cmd

# Import Python standard modules
from datetime import datetime
import os
import time

# Import third party modules
import psutil   # https://pypi.org/project/psutil/


def main():
    """Main entry point for the repo-converter container."""

    # Set up initial counters and datetimes
    run_count = 0
    start_datetime = datetime.fromtimestamp(psutil.Process().create_time()).strftime("%Y-%m-%d %H:%M:%S")

    # Read env vars
    env_vars = env.load_env_vars()

    # Configure logging
    utils.logging.configure_logging(env_vars['LOG_LEVEL'])

    # Log the container start event
    log("repo-converter started", "INFO")

    # Main loop
    while True:

        # Increment the run count, and update the uptime
        run_count += 1
        uptime = cmd.get_pid_uptime()

        # Log the start of the run
        log(f"Starting run {run_count}, container uptime: {uptime}; container running since {start_datetime} with args: {str(env_vars)}; container ID: {os.uname().nodename}", "info")

        # Configure git to trust all directories
        git_config_safe_directory()

        # Parse the repos to convert file
        repos_to_convert = parse_repos_to_convert_file(env_vars["REPOS_TO_CONVERT"])

        # Log the end of the run
        log(f"Finishing run {run_count}, container uptime: {uptime}; container running since {start_datetime} with args: {str(env_vars)}; container ID: {os.uname().nodename}", "info")

        # Sleep the configured interval
        log(f"Sleeping main loop for REPO_CONVERTER_INTERVAL_SECONDS={env_vars['REPO_CONVERTER_INTERVAL_SECONDS']} seconds", "info")
        time.sleep(env_vars["REPO_CONVERTER_INTERVAL_SECONDS"])

    # Log the exit event
    # This should never be reached
    log("repo-converter exiting", "INFO")

if __name__ == "__main__":
    main()
