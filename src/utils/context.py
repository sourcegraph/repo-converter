#!/usr/bin/env python3
# Context class for managing application state across modules

# Note: The logger imports this module
# Do not import the logger module; it'd create a circular import

# Import Python standard modules
from datetime import datetime
import os

# Import third party modules
import psutil # https://pypi.org/project/psutil/


class Context:
    """
    Central context class for managing application state across all modules.
    Encapsulates shared state that needs to be passed between different parts of the application.
    """

    # repos-to-convert.yaml file contents
    repos = {}


    def __init__(self, env_vars):
        """
        Initialize the converter context with environment variables and default state.

        Args:
            env_vars: dict of environment variables from the config.load_env_vars() function
        """

        # Environment variables
        self.env_vars = env_vars

        # Container metadata
        self.container_id = os.uname().nodename
        self.start_datetime = datetime.fromtimestamp(psutil.Process().create_time()).strftime("%Y-%m-%d %H:%M:%S")

        # Child processes
        self.child_procs = {}

        # Set of secrets to redact in logs
        self.secrets = set()

        # Run count
        self.run_count = 0

        # Namespace for our metadata in git repo config files
        self.git_config_namespace = "repo-converter"


    def increment_run_count(self):
        """Increment the run counter and return the new count."""
        self.run_count += 1
        return self.run_count


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


    def update_repos(self, repos_dict):
        """
        Update the repositories to convert dictionary.

        Args:
            repos_dict (dict): Dictionary of repositories to convert
        """
        self.repos_to_convert_dict = repos_dict


    def get_run_log_string(self):
        """
        Generate a standardized log string with container and run information.

        Returns:
            str: Formatted log string with container metadata
        """
        return f"container ID: {self.container_id}; container running since {self.start_datetime}; with args: {str(self.env_vars)}"


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
