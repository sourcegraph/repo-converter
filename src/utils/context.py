#!/usr/bin/env python3
# Context class for managing application state across modules

# Note: The logger imports this module
# Do not import the logger module; it'd create a circular import

# Import Python standard modules
from datetime import datetime
import os
import psutil
import time


class Context:
    """
    Central context class for managing application state across all modules.
    Encapsulates shared state that needs to be passed between different parts of the application.
    """

    ### Class attributes

    ## Static / empty

    # Child process tracking for convert_repos.py module's function calls
    active_multiprocessing_jobs = []

    # Child process tracking for cmd.py module's external commands
    child_procs = {}

    # Run count
    cycle = 0

    # Namespace for our metadata in git repo config files
    git_config_namespace = "repo-converter"

    # Attributes we'd like to log for each process
    process_attributes_to_log = [
        "args",
        "cmdline",
        "cpu_times",
        "end_time",
        "memory_info",
        "memory_percent",
        "net_connections_count",
        "net_connections",
        "num_fds",
        "open_files",
        "pid",
        "ppid",
        "pgroup", "pgid", # Not implemented in psutils, need to use os.getpgid, https://github.com/giampaolo/psutil/issues/697#issuecomment-457302655
        "execution_time",
        "start_time",
        "status",
        "threads",
    ]

    # repos-to-convert.yaml file contents
    repos = {}

    # Set of secrets to redact in logs
    secrets = set()


    ## Set on container startup

    # Container metadata (set per-instance in __init__)
    container_id = None
    env_vars = None
    resuid = None
    start_datetime = None
    start_timestamp = None

    # Subset of process_attributes_to_log, filled by list(psutil.Process().as_dict().keys()) in self.initialize_process_attributes_to_fetch()
    process_attributes_to_fetch = []

    # Track concurrency state in the context object
    concurrency_manager = None


    ## Class member functions


    def __init__(self, env_vars):
        """
        Initialize the converter context with environment variables and default state.

        Args:
            env_vars: dict of environment variables from the config.load_env_vars() function
        """

        # Store environment variables from context initialization call
        self.env_vars = env_vars

        # Set container metadata (per-instance, not shared across instances)
        self.container_id = os.uname().nodename
        self.resuid = os.getresuid()
        self.start_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.start_timestamp = time.time()

        # Get the list of proc attributes from the psutils library, and initialize process_attributes_to_fetch
        self.initialize_process_attributes_to_fetch()


    def add_secrets(self, new_secrets):
        """
        Add new secrets to the context's secret tracking.

        Args:
            new_secrets (set or iterable): New secrets to add to tracking
        """
        if isinstance(new_secrets, set):
            self.secrets.update(new_secrets)
        else:
            self.secrets.add(new_secrets)


    def get_env_var(self, key, default=None):
        """
        Get an environment variable value with optional default.

        Args:
            key (str): Environment variable key
            default: Default value if key not found

        Returns:
            Environment variable value or default
        """
        return self.env_vars.get(key, default)


    def increment_cycle(self):
        """Increment the run counter and return the new count."""
        self.cycle += 1
        return self.cycle


    def initialize_process_attributes_to_fetch(self):
        """
        Of the psutils Process object attributes we'd like to fetch, which of them are available in the current version of the psutil library?
        """

        psutil_attributes = list(psutil.Process().as_dict().keys())

        for attribute in self.process_attributes_to_log:
            if attribute in psutil_attributes:
                self.process_attributes_to_fetch.append(attribute)


    def update_repos(self, repos_dict):
        """
        Update the repositories to convert dictionary.

        Args:
            repos_dict (dict): Dictionary of repositories to convert
        """
        self.repos_to_convert_dict = repos_dict
