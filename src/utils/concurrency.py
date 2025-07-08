#!/usr/bin/env python3
# Concurrency manager class, to limit the number of concurrent repo conversion jobs
# Only one instance of this class should exist, in main.py's initialization steps

# Need to be careful with log(..., log_concurrency_status=True), as then the log module calls the get_status() function in this class and creates a deadlock

# Import repo-converter modules
from utils.context import Context
from utils.log import log

# Import Python standard modules
import multiprocessing


class ConcurrencyManager:
    """
    Manages concurrency limits for repo conversion jobs.
    Enforces both global and per-server limits using semaphores.
    """

    def __init__(self, ctx: Context):

        # Create a copy of the Context, so that member functions can be called with self, instead of ctx
        self.ctx = ctx

        # Create member attributes with shorter names
        self.global_limit = self.ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_GLOBAL"]
        self.per_server_limit = self.ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_PER_SERVER"]

        # Create global semaphore to track all concurrent jobs
        self.global_semaphore = multiprocessing.Semaphore(self.global_limit)

        # Per-server semaphores
        # Created dynamically as needed, as the repos-to-convert.yaml file can be changed,
        # and new servers can be added, while the container is running
        # Keys: server_name
        # Values: semaphore object, which seems to be an integer, counting down from (MAX_CONCURRENT_CONVERSIONS_PER_SERVER - 1) to 0
        self.per_server_semaphores = {}

        # Protect the per_server_semaphores dict, by ensuring no two processes can write to it at the same time
        # This seems unnecessary, as only the convert_repos.start() function in the main process should be calling these functions
        self.per_server_semaphores_lock = multiprocessing.Lock()

        # Create a manager object to share and sync data between processes
        # What data should be stored in the Manager?
        # What data do the repo sync jobs need to share back to the parent process, while running?
        self.manager = multiprocessing.Manager()

        # Share a list of active jobs with concurrency_monitor
        # Keys: server_name
        # Values: [list of repos with active jobs]
        self.active_jobs = self.manager.dict()

        # Ensure no two processes can write to active_jobs at the same
        self.active_jobs_lock = multiprocessing.Lock()

        structured_data_to_log = {
            "concurrency": {
                "MAX_CONCURRENT_CONVERSIONS_GLOBAL": self.global_limit,
                "MAX_CONCURRENT_CONVERSIONS_PER_SERVER": self.per_server_limit
            }
        }

        # Log this, without log_concurrency_status=True, as that creates a race condition
        log(ctx, f"Initialized concurrency manager", "debug", structured_data_to_log)


    def acquire_job_slot(self, repo_key: str, server_name: str, timeout: float = 10.0) -> bool:
        """
        Check if:
        - Repo already has a job in progress
        - Global and server semaphore slots are available
        Try to acquire both global and server-specific semaphores
        Returns True if:
        - Successfully got a job slot
        Returns False if:
        - Repo already has a job in progress
        """

        ## Check if this repo already has a job in progress
        # TODO: Remove the duplicate logic in svn.py, and integrate the missing bits in here

        server_active_jobs_list = []
        with self.active_jobs_lock:

            # active_jobs is a dict, with subdicts for each server_name, which contains a list of active jobs for that server
            if server_name in self.active_jobs:

                server_active_jobs_list = list(self.active_jobs[server_name])

        if repo_key in server_active_jobs_list:

            log(self.ctx, f"{repo_key}; {server_name}; Repo job already in progress", "info")
            return False


        ## Check per-server limit
        # Get the semaphore object for this server
        server_semaphore = self.get_server_semaphore(server_name)

        # Check the semaphore value for number of remaining slots
        if server_semaphore.get_value() <= 0:
            log(self.ctx, f"{repo_key}; MAX_CONCURRENT_CONVERSIONS_PER_SERVER={self.per_server_limit} reached for server {server_name}, waiting for a slot", "info")

        ## Check global limit
        if self.global_semaphore.get_value() <= 0:
            log(self.ctx, f"{repo_key}; MAX_CONCURRENT_CONVERSIONS_GLOBAL={self.global_limit} reached, waiting for a slot", "info")


        ## Acquire a slot in the the server-specific semaphore
        # Want to block, so that the main loop has to wait until all repos get a chance to run through before finishing
        # TODO: Determine if this would build an infinite queue of jobs, ballooning memory usage, if job execution time is longer than REPO_CONVERTER_INTERVAL_SECONDS
        if not server_semaphore.acquire(block=True):

            log(self.ctx, f"{repo_key}; server_semaphore.acquire failed", "error")
            return False

        ## Acquire a slot in the the global semaphore
        # Want to block, so that the main loop has to wait until all repos get a chance to run through before finishing
        # TODO: Determine if this would build an infinite queue of jobs, ballooning memory usage, if job execution time is longer than REPO_CONVERTER_INTERVAL_SECONDS
        if not self.global_semaphore.acquire(block=True):

            # Release the server semaphore since we couldn't get the global one
            server_semaphore.release()

            log(self.ctx, f"{repo_key}; self.global_semaphore.acquire failed", "error")
            return False

        ## Successfully acquired both semaphores

        # Add the active job to the active_jobs dict
        server_active_jobs_list = []
        with self.active_jobs_lock:

            # If the server doesn't already have a list, then create one
            if server_name not in self.active_jobs:
                self.active_jobs[server_name] = self.manager.list()

            # Read it into a normal list
            server_active_jobs_list = list(self.active_jobs[server_name])

            # Append the repo key
            server_active_jobs_list.append(repo_key)

            # Sort the list
            server_active_jobs_list.sort()

            # Assign the list back to the manager list
            self.active_jobs[server_name] = server_active_jobs_list

        # Log an update
        log(self.ctx, f"{repo_key}; Acquired job slot for server {server_name}", "debug")

        return True


    def get_server_semaphore(self, server_name: str):
        """Get or create a semaphore for the given server."""

        # Wait for the lock to be free
        with self.per_server_semaphores_lock:

            # self.per_server_semaphores dict keys are server_name
            # If the dict doesn't already have a semaphore in the dict
            if server_name not in self.per_server_semaphores:

                # Then create one
                # TODO: Get the limit for this server from the repos-to-convert.yaml file,
                # but not sure if this value can be changed without restarting the container
                self.per_server_semaphores[server_name] = multiprocessing.Semaphore(self.per_server_limit)
                log(self.ctx, f"Created semaphore for server {server_name} with limit {self.per_server_limit}", "debug")

            # Whether the server already had a semaphore in the dict, or one was just created for it, return the semaphore object
            return self.per_server_semaphores[server_name]


    def get_status(self) -> dict:
        """
        Get current concurrency status for monitoring.

        Called by log()
        """

        # Create status dict to be returned
        status = {
            "global": {
                "active": "",
                "available": "",
                "limit": self.global_limit
            },
            "servers": {}
        }

        # Fill in global fields
        status["global"]["active"]      = self.global_limit - self.global_semaphore.get_value()
        status["global"]["available"]   = self.global_semaphore.get_value()

        # Fill in servers fields
        # Get the lock on per_server_semaphores_lock,
        # to ensure that the values are not changing as this is reading them
        with self.per_server_semaphores_lock:

            # This indicates that the per_server_semaphores dict's items should be
            # tuples of server hostnames, and their respective semaphores
            for server_name, per_server_semaphore in self.per_server_semaphores.items():

                # Get the lock on the active_jobs dict as well,
                # to ensure that the values are not changing as this is reading them
                # Not sure why to get and release the same lock for each server,
                # to ensure this function doesn't hold the lock for too long?
                with self.active_jobs_lock:

                    # The active jobs dict, seems to have the server hostname as keys
                    # Copy the dict, to free up the lock ASAP
                    # active_jobs_list = list(self.active_jobs[server_name]).sort()
                    active_jobs_list = list(self.active_jobs[server_name])

                status["servers"][server_name] = {
                    "active": self.per_server_limit - per_server_semaphore.get_value(),
                    "available": per_server_semaphore.get_value(),
                    "limit": self.per_server_limit,
                    "active_jobs": active_jobs_list
                }

        # Return the status dict
        return status


    def release_job_slot(self, repo_key: str, server_name: str):
        """Release both global and server-specific semaphores."""

        server_active_jobs_list = []

        with self.active_jobs_lock:

            # Read it into a normal list
            server_active_jobs_list = list(self.active_jobs[server_name])

            # Remove the repo from the active_jobs list
            if repo_key in server_active_jobs_list:
                server_active_jobs_list.remove(repo_key)

            # Overwrite the managed list
            self.active_jobs[server_name] = server_active_jobs_list


        try:

            # Release per-server semaphore
            server_semaphore = self.get_server_semaphore(server_name)
            server_semaphore.release()

            # Release global semaphore
            self.global_semaphore.release()

            log(self.ctx, f"{repo_key}; Released job slot for server {server_name}", "debug")

        except ValueError as e:
            log(self.ctx, f"{repo_key}; Error releasing semaphores: {e}", "error")
