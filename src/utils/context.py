#!/usr/bin/env python3
# Context class for managing application state across modules

# Note: The logger imports this module
# Do not import the logger module; it'd create a circular import

# Import Python standard modules
from datetime import datetime
import json
import os
import psutil

class Context:
    """
    Central context class for managing application state across all modules.
    Encapsulates shared state that needs to be passed between different parts of the application.
    """

    ## Class attributes

    # repos-to-convert.yaml file contents
    repos = {}

    # Child process tracking
    child_procs = {}

    # Set of secrets to redact in logs
    secrets = set()

    # Run count
    run_count = 0

    # Namespace for our metadata in git repo config files
    git_config_namespace = "repo-converter"

    # Container metadata
    container_id = os.uname().nodename
    start_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    process_attributes_to_log = [
        "args",
        "cmdline",
        "connections_count",
        "connections",
        "cpu_times",
        "end_time",
        "memory_percent",
        "name",
        "net_connections",
        "num_fds",
        "open_files",
        "pid",
        "ppid",
        "run_time",
        "start_time",
        "status",
    ]

    # Subset of process_attributes_to_log, filled by list(psutil.Process().as_dict().keys()) in self.initialize_process_attributes_to_fetch()
    process_attributes_to_fetch = []


    ## Class member functions


    def __init__(self, env_vars):
        """
        Initialize the converter context with environment variables and default state.

        Args:
            env_vars: dict of environment variables from the config.load_env_vars() function
        """

        # Store environment variables from context initialization call
        self.env_vars = env_vars

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


    def get_run_log_string(self):
        """
        Generate a standardized log string with container and run information.

        Returns:
            str: Formatted log string with container metadata
        """
        return f"container ID: {self.container_id}; container running since {self.start_datetime}; with env vars: {json.dumps(self.env_vars, indent = 4, sort_keys=True)}"


    def increment_run_count(self):
        """Increment the run counter and return the new count."""
        self.run_count += 1
        return self.run_count


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
