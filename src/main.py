#!/usr/bin/env python3
# Entry point for the repo-converter container

# Import repo-converter modules
from config import env, repos_to_convert
from source_repo import convert_repos
from utils import cmd, git, lock, logger, secret
from utils.logger import log

# Import Python standard modules
from datetime import datetime
import os
import time

# Import third party modules
import psutil # https://pypi.org/project/psutil/


def main():
    """Main entry point for the repo-converter container"""

    # Set up initial metadata
    container_id = os.uname().nodename
    run_count = 0
    start_datetime = datetime.fromtimestamp(psutil.Process().create_time()).strftime("%Y-%m-%d %H:%M:%S")

    # Load environment variables from the container's running environment into env_vars dict
    env_vars = env.load_env_vars()

    # Configure logging
    logger.configure_logging(env_vars['LOG_LEVEL'])

    # DRY run log string
    run_log_string = f"container ID: {container_id}; container running since {start_datetime}; with args: {str(env_vars)}"

    # Log the container start event
    log(f"Starting container; {run_log_string}", "INFO")

    # Top level dict for tracking child process state
    child_procs = {}

    # Top level set to track secrets
    secrets = set()

    # Application main loop
    while True:

        # Increment the run count, and update the uptime for this process (PID 1)
        run_count += 1

        if env_vars['MAX_CYCLES'] != "" and run_count > int(env_vars['MAX_CYCLES']):
            log(f"Reached MAX_CYCLES={env_vars['MAX_CYCLES']}, exiting loop","WARNING")
            break

        uptime = cmd.get_pid_uptime()

        # Log the start of the run
        log(f"Starting run {run_count}; container uptime: {uptime}", "info")

        # Load the repos to convert from file
        repos_to_convert_dict = repos_to_convert.load_from_file(env_vars)

        # Add the secrets from the repos to convert file to the secrets set
        secrets.add(secret.get_secrets_from_repos_to_convert(repos_to_convert_dict))

        # Tidy up zombie processes from the previous run through this loop
        child_procs = cmd.status_update_and_cleanup_zombie_processes(child_procs)

        # Disable git safe directory, to workaround "dubious ownership" errors
        git.git_config_safe_directory()

        # Run the main application logic
        child_procs = convert_repos.convert(repos_to_convert_dict, child_procs)

        # Tidy up zombie processes which have already completed during this run through this loop
        child_procs = cmd.status_update_and_cleanup_zombie_processes(child_procs)

        # Log the end of the run
        uptime = cmd.get_pid_uptime()
        log(f"Finishing run {run_count}; container uptime: {uptime}", "info")

        # Sleep the configured interval
        log(f"Sleeping main loop for REPO_CONVERTER_INTERVAL_SECONDS={env_vars['REPO_CONVERTER_INTERVAL_SECONDS']} seconds", "info")
        time.sleep(env_vars["REPO_CONVERTER_INTERVAL_SECONDS"])

    # Log the exit event
    uptime = cmd.get_pid_uptime()
    log(f"Stopping container; container uptime: {uptime}; {run_log_string}", "WARNING")

if __name__ == "__main__":
    main()
