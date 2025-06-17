#!/usr/bin/env python3
# Concurrency manager class, to limit the number of concurrent repo conversion jobs
# One instance of this class should exist, in main.py's initialization steps

# Import repo-converter modules
from utils.context import Context
from utils.log import log

# Import Python standard modules
from urllib.parse import urlparse
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
        self.global_limit = self.ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_TOTAL"]
        self.per_server_limit = self.ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_PER_SERVER"]

        # Create global semaphore for total concurrent jobs
        self.global_semaphore = multiprocessing.Semaphore(self.global_limit)

        # Per-server semaphores
        # Created dynamically as needed, as the repos-to-convert.yaml file can be changed,
        # and new servers can be added, while the container is running
        # Keys: server_hostname
        # Values: semaphore object
        self.per_server_semaphores = {}

        # Protect the per_server_semaphores dict, by ensuring no two processes can write to it at the same time
        # This seems unnecessary, as only the convert_repos.start() function in the main process should be calling these functions
        self.per_server_semaphores_lock = multiprocessing.Lock()

        # Create a manager object to share and sync data between processes
        # What data should be stored in the Manager?
        # What data do the repo sync jobs need to share back to the parent process, while running?
        self.manager = multiprocessing.Manager()

        # Share a list of active jobs with concurrency_monitor
        # Keys: server_hostname
        # Values: [list of repos with active jobs]
        self.active_jobs = self.manager.dict()

        # Ensure no two processes can write to active_jobs at the same
        self.active_jobs_lock = multiprocessing.Lock()

        log(ctx, f"Initialized concurrency manager: MAX_CONCURRENT_CONVERSIONS_TOTAL={self.global_limit}, MAX_CONCURRENT_CONVERSIONS_PER_SERVER={self.per_server_limit}", "debug")


    def acquire_job_slot(self, repo_key: str, server_hostname: str, timeout: float = 10.0) -> bool:
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

        # Check if repo already has a job in progress
        server_active_jobs_list = []
        with self.active_jobs_lock:
            if server_hostname in self.active_jobs:
                server_active_jobs_list = list(self.active_jobs[server_hostname])
        if repo_key in server_active_jobs_list:
            log(self.ctx, f"{repo_key}; Repo job already in progress", "info")
            return False

        # Check global limit
        if self.global_semaphore.get_value() <= 0:
            log(self.ctx, f"{repo_key}; MAX_CONCURRENT_CONVERSIONS_TOTAL={self.global_limit} reached, waiting for a slot", "info")

        # Check per-server limit

        # Get the semaphore object for this server
        server_semaphore = self.get_server_semaphore(server_hostname)

        # Check the semaphore value for number of remaining slots
        if server_semaphore.get_value() <= 0:
            log(self.ctx, f"{repo_key}; MAX_CONCURRENT_CONVERSIONS_PER_SERVER={self.per_server_limit} reached, waiting for a slot", "info")

        # Acquire a slot in the global semaphore
        # if not self.global_semaphore.acquire(block=False, timeout=timeout):
        # Want to block, so that the main loop has to wait until all repos get a chance to run through before finishing
        if not self.global_semaphore.acquire(block=True):

            # TODO: Want to hold this semaphore request in a queue, so that repo sync jobs are executed in a predictable order,
            # not just whichever repo sync job happened to be requested after the [limit]'th job finished
            log(self.ctx, f"{repo_key}; self.global_semaphore.acquire failed", "error")
            return False

        # Get the semaphore object for this server
        server_semaphore = self.get_server_semaphore(server_hostname)

        # Try to acquire server-specific semaphore
        #if not server_semaphore.acquire(block=False, timeout=timeout):
        # Want to block, so that the main loop has to wait until all repos get a chance to run through before finishing
        if not server_semaphore.acquire(block=True):

            # Release the global semaphore since we couldn't get the server one
            self.global_semaphore.release()

            # TODO: Want to hold this semaphore request in a queue, so that repo sync jobs are executed in a predictable order,
            # not just whichever repo sync job happened to be requested after the [limit]'th job finished

            log(self.ctx, f"{repo_key}; server_semaphore.acquire failed", "error")
            return False

        # Successfully acquired both semaphores

        # Add the active job to the active_jobs dict
        with self.active_jobs_lock:

            # If the server doesn't already have a list, then create one
            if server_hostname not in self.active_jobs:
                self.active_jobs[server_hostname] = self.manager.list()

            # Append the repo to the list, now that we're confident it exists
            self.active_jobs[server_hostname].append(repo_key)

        # Get the n / limit, where n is the n'th slot this job got on the global semaphore, if limit is set
        global_status = f"{self.global_limit - self.global_semaphore.get_value()}/{self.global_limit}"
        server_status = f"{self.per_server_limit - server_semaphore.get_value()}/{self.per_server_limit})"

        # Log an update
        log(self.ctx, f"{repo_key}; Acquired job slot for server {server_hostname} (global: {global_status}, server: {server_status}", "info")

        return True


    def extract_server_host(self, repo_config: dict) -> str:
        """Extract server hostname from repos-to-convert dict."""

        # Try to get from svn-repo-code-root URL
        # TODO: Make the repos-to-convert.yaml key more generic for other code host types
        repo_url = repo_config.get("svn-repo-code-root", "")
        if repo_url:
            try:
                parsed = urlparse(repo_url)
                if parsed.hostname:
                    return parsed.hostname
            except Exception as e:
                log(self.ctx, f"Failed to parse URL {repo_url}: {e}", "warning")

        # Fallback to code-host-name if provided
        code_host = repo_config.get("code-host-name", "")
        if code_host:
            return code_host

        # Last resort: use "unknown"
        log(self.ctx, f"Could not determine server host for repo config: {repo_config}", "warning")
        return "unknown"


    def get_server_semaphore(self, server_hostname: str):
        """Get or create a semaphore for the given server."""

        # Wait for the lock to be free
        with self.per_server_semaphores_lock:

            # self.per_server_semaphores dict keys are server_hostname
            # If the dict doesn't already have a semaphore in the dict
            if server_hostname not in self.per_server_semaphores:

                # Then create one
                # TODO: Get the limit for this server from the repos-to-convert.yaml file,
                # but not sure if this value can be changed without restarting the container
                self.per_server_semaphores[server_hostname] = multiprocessing.Semaphore(self.per_server_limit)
                log(self.ctx, f"Created semaphore for server {server_hostname} with limit {self.per_server_limit}", "debug")

            # Whether the server already had a semaphore in the dict, or one was just created for it, return the semaphore object
            return self.per_server_semaphores[server_hostname]


    def get_status(self) -> dict:
        """Get current concurrency status for monitoring."""

        # Create status dict to be returned
        status = {
            "global": {
                "active_slots": "",
                "available_slots": "",
                "limit": self.global_limit
            },
            "servers": {}
        }

        # Fill in global fields
        status["global"]["active_slots"]      = self.global_limit - self.global_semaphore.get_value()
        status["global"]["available_slots"]   = self.global_semaphore.get_value()

        # Fill in servers fields
        # Get the lock on per_server_semaphores_lock,
        # to ensure that the values are not changing as this is reading them
        with self.per_server_semaphores_lock:

            # This indicates that the per_server_semaphores dict's items should be
            # tuples of server hostnames, and their respective semaphores
            for server_hostname, per_server_semaphore in self.per_server_semaphores.items():

                # Get the lock on the active_jobs dict as well,
                # to ensure that the values are not changing as this is reading them
                # Not sure why to get and release the same lock for each server,
                # to ensure this function doesn't hold the lock for too long?
                with self.active_jobs_lock:

                    # The active jobs dict, seems to have the server hostname as keys
                    # Copy the dict, to free up the lock ASAP
                    active_jobs_list = list(self.active_jobs[server_hostname])

                status["servers"][server_hostname] = {
                    "active_slots": self.per_server_limit - per_server_semaphore.get_value(),
                    "available_slots": per_server_semaphore.get_value(),
                    "limit": self.per_server_limit,
                    "active_jobs": active_jobs_list
                }

        # Return the status dict
        return status


    def release_job_slot(self, repo_key: str, server_hostname: str):
        """Release both global and server-specific semaphores."""

        try:
            with self.active_jobs_lock:
                if repo_key in self.active_jobs[server_hostname]:
                    self.active_jobs[server_hostname].remove(repo_key)

            # Release per-server semaphore
            server_semaphore = self.get_server_semaphore(server_hostname)
            server_semaphore.release()

            # Release global semaphore
            self.global_semaphore.release()

            log(self.ctx, f"{repo_key}; Released job slot for server {server_hostname}", "info")

        except ValueError as e:
            log(self.ctx, f"{repo_key}; Error releasing semaphores: {e}", "error")
