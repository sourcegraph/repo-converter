#!/usr/bin/env python3
# Context class for managing application state across modules

# Note: The log module imports this module
# Do not import the log module; it'd create a circular import

# Import Python standard modules
from collections import defaultdict
from datetime import datetime
import os
import psutil
import time

class NestedDefaultDict(defaultdict):
    """
    Helper class to prevent KeyErrors on job dict
    """
    def __init__(self, *args, **kwargs):
        super(NestedDefaultDict, self).__init__(NestedDefaultDict, *args, **kwargs)

    def __repr__(self):
        return repr(dict(self))

class Context:
    """
    Central context class for managing application state across all modules.
    Encapsulates shared state that needs to be passed between different parts of the application.
    """

    ### Class attributes

    ## Static / empty

    # Child process tracking for convert_repos.py module's function calls
    active_repo_conversion_processes = []

    # Child process tracking for cmd.py module's external commands
    child_procs = {}

    # Run count
    cycle = 0

    # Shutdown flag for graceful termination
    shutdown_flag = False

    # Namespace for our metadata in git repo config files
    git_config_namespace = "repo-converter"

    # Attributes we'd like to log for each process
    psutils_process_attributes_to_fetch = [
        'cmdline',
        'cpu_percent',
        'cpu_times',
        'create_time', # Seconds since Epoch, need to convert to datetime
        'exe',
        'io_counters',
        'memory_full_info',
        # 'memory_maps', # May be useful for deeper debugging, but is quite noisy when not needed
        'memory_percent',
        'net_connections',
        'num_fds',
        'num_threads',
        'open_files',
        'pid',
        'ppid',
        'status',
        'threads',
    ]

    # repos-to-convert.yaml file contents
    repos = {}

    # Space to store structure log information for repo sync jobs
    # job = {}
    job = NestedDefaultDict()

    # Set of secrets to redact in logs
    secrets = set()

    # List of fields, in priority order, which may have a URL, to try and extract a hostname from for max_concurrent_conversions_server_name
    # TODO: Add more field names for more repo types as needed in repos-to-convert.yaml
    url_fields = [
        "repo-url",
        "repo-parent-url",
        "svn-repo-code-root",
    ]


    ## Set on container startup

    # Container metadata (set per-instance in __init__)
    container_id = None
    env_vars = None
    resuid = None
    start_datetime = None
    start_timestamp = None

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

        # Get the list of proc attributes from the psutils library, and initialize psutils_process_attributes_to_fetch
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

        for attribute in self.psutils_process_attributes_to_fetch:
            if attribute not in psutil_attributes:
                self.psutils_process_attributes_to_fetch.remove(attribute)


    def reset_job(self):
        """
        Resets the job dict for each repo conversion job,
        to prevent log events from including old data from other jobs
        """

        self.job = NestedDefaultDict()

        # self.job = {
        #     "job": {
        #         "id": "",
        #         "config": {
        #             "repo_key": "",
        #             "repo_type": "",
        #             "server_name": ""
        #         },
        #         "result": {
        #             "action": "",
        #             "reason": "",
        #             "success": "",
        #             "run_time_seconds": "",
        #         },
        #         "stats": {
        #             "local": {},
        #             "remote": {}
        #         }
        #     }
        # }

    def update_repos(self, repos_dict):
        """
        Update the repositories to convert dictionary.

        Args:
            repos_dict (dict): Dictionary of repositories to convert
        """
        self.repos_to_convert_dict = repos_dict
