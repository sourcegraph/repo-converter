#!/usr/bin/env python3
# Concurrency manager class, to limit the number of concurrent repo conversion jobs
# Only one instance of this class should exist, in main.py's initialization steps

# Need to be careful with log(..., log_concurrency_status=True), as then the log module calls the get_status() function in this class and creates a deadlock

# Import repo-converter modules
from utils.context import Context
from utils.log import log

# Import Python standard modules
from datetime import datetime
import multiprocessing
import time

class ConcurrencyManager:
    """
    Manages concurrency limits for repo conversion jobs.
    Enforces both global and per-server limits using semaphores.
    """

    # Create a manager object to share and sync data between processes
    manager = multiprocessing.Manager()

    # # Create member attributes with shorter names
    # global_limit = ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_GLOBAL"]
    # per_server_limit = ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_PER_SERVER"]

    # # Update global semaphore with the global_limit from the env vars
    global_semaphore = multiprocessing.Semaphore()

    # Per-server semaphores
    # Created dynamically as needed, as the repos-to-convert.yaml file can be changed,
    # and new servers can be added, while the container is running
    # Keys: server_name
    # Values: semaphore object, which seems to be an integer, counting down from (MAX_CONCURRENT_CONVERSIONS_PER_SERVER - 1) to 0
    # Can't create this as a type manager.dict(), that throws an error
    per_server_semaphores = {}
    # Protect the per_server_semaphores dict, by ensuring no two processes can write to it at the same time
    # This seems unnecessary, as only the convert_repos.start() function in the main process should be calling these functions
    per_server_semaphores_lock = multiprocessing.Lock()

    # Share a list of active jobs with concurrency_monitor
    active_jobs = manager.dict() # server_name -> list of (active_job_id, active_job_repo, active_job_timestamp)
    # Ensure no two processes can write to active_jobs at the same
    active_jobs_lock = multiprocessing.Lock()

    # Track jobs waiting for a semaphore to become available, using a list for each server_name, not sure why
    queued_jobs = manager.dict()  # server_name -> list of (queued_job_id, queued_job_repo, queued_job_timestamp)
    queued_jobs_lock = multiprocessing.Lock()


    def __init__(self, ctx: Context):

        # # Create a manager object to share and sync data between processes
        # self.manager = multiprocessing.Manager()

        # Create member attributes with shorter names
        self.global_limit = ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_GLOBAL"]
        self.per_server_limit = ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_PER_SERVER"]

        # Update global semaphore with the global_limit from the env vars
        self.global_semaphore = multiprocessing.Semaphore(self.global_limit)

        # # Per-server semaphores
        # # Created dynamically as needed, as the repos-to-convert.yaml file can be changed,
        # # and new servers can be added, while the container is running
        # # Keys: server_name
        # # Values: semaphore object, which seems to be an integer, counting down from (MAX_CONCURRENT_CONVERSIONS_PER_SERVER - 1) to 0
        # # Can't create this as a type self.manager.dict(), that throws an error
        # self.per_server_semaphores = {}
        # # Protect the per_server_semaphores dict, by ensuring no two processes can write to it at the same time
        # # This seems unnecessary, as only the convert_repos.start() function in the main process should be calling these functions
        # self.per_server_semaphores_lock = multiprocessing.Lock()

        # # Share a list of active jobs with concurrency_monitor
        # self.active_jobs = self.manager.dict() # server_name -> list of (active_job_id, active_job_repo, active_job_timestamp)
        # # Ensure no two processes can write to active_jobs at the same
        # self.active_jobs_lock = multiprocessing.Lock()

        # # Track jobs waiting for a semaphore to become available, using a list for each server_name, not sure why
        # self.queued_jobs = self.manager.dict()  # server_name -> list of (queued_job_id, queued_job_repo, queued_job_timestamp)
        # self.queued_jobs_lock = multiprocessing.Lock()

        # Log this, without log_concurrency_status=True, as that creates a race condition
        # structured_data_to_log = {
        #     "concurrency": {
        #         "MAX_CONCURRENT_CONVERSIONS_GLOBAL": self.global_limit,
        #         "MAX_CONCURRENT_CONVERSIONS_PER_SERVER": self.per_server_limit
        #     }
        # }
        # log(ctx, f"Initialized concurrency manager", "debug", structured_data_to_log)


    def acquire_job_slot(self, ctx: Context) -> bool:
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

        # Get job information from context
        this_job_id         = ctx.job["job"]["id"]
        this_job_repo       = ctx.job["job"]["repo_key"]
        this_job_timestamp  = int(time.time())
        server_name         = ctx.job["job"]["server_name"]


        ## Check if this repo already has a job in progress
        # TODO: Remove the duplicate logic in svn.py, and integrate the missing bits in here
        with self.active_jobs_lock:

            # active_jobs is a dict, with subdicts for each server_name, which contains a list of active jobs for that server
            if server_name in self.active_jobs:

                for active_job_id, active_job_repo, active_job_timestamp in self.active_jobs[server_name]:

                    if active_job_repo == this_job_repo:
                        log(ctx, f"Skipping; Repo job already in progress; repo: {active_job_repo}, timestamp: {active_job_timestamp}; job_id: {active_job_id}; running for: {int(time.time() - active_job_timestamp)} seconds", "info")
                        return False

        ## Add this job to the dict of waiting jobs, just in case the blocking semaphore acquire takes a while
        with self.queued_jobs_lock:

            if server_name not in self.queued_jobs:
                self.queued_jobs[server_name] = self.manager.list()

            queued_jobs_list = self.queued_jobs[server_name]
            queued_jobs_list.append((this_job_id, this_job_repo, this_job_timestamp))
            self.queued_jobs[server_name] = queued_jobs_list

        ## Check per-server limit
        # Get the semaphore object for this server
        server_semaphore = self._get_server_semaphore(ctx)

        # Check the semaphore value for number of remaining slots
        if server_semaphore.get_value() <= 0:
            log(ctx, f"Hit per-server concurrency limit; MAX_CONCURRENT_CONVERSIONS_PER_SERVER={self.per_server_limit}, waiting for a server slot", "info")

        ## Check global limit
        if self.global_semaphore.get_value() <= 0:
            log(ctx, f"Hit global concurrency limit; MAX_CONCURRENT_CONVERSIONS_GLOBAL={self.global_limit}, waiting for a slot", "info")

        ## Acquire a slot in the the server-specific semaphore
        # Want to block, so that the main loop has to wait until all repos get a chance to run through before finishing
        if not server_semaphore.acquire(block=True):

            log(ctx, "server_semaphore.acquire failed", "error")
            return False

        ## Acquire a slot in the the global semaphore
        # Want to block, so that the main loop has to wait until all repos get a chance to run through before finishing
        if not self.global_semaphore.acquire(block=True):

            # Release the server semaphore since we couldn't get the global one
            server_semaphore.release()

            log(ctx, "self.global_semaphore.acquire failed", "error")
            return False

        ## Successfully acquired both semaphores

        # Add the active job to the active_jobs dict
        with self.active_jobs_lock:

            # If the server doesn't already have a list, then create one
            if server_name not in self.active_jobs:
                self.active_jobs[server_name] = self.manager.list()

            # Read it into a normal list
            server_active_jobs_list = self.active_jobs[server_name]

            # Append the new job
            server_active_jobs_list.append((this_job_id, this_job_repo, this_job_timestamp))

            # Assign the list back to the manager list
            self.active_jobs[server_name] = server_active_jobs_list

        # Remove the job from the queued jobs list
        with self.queued_jobs_lock:

            # Get the managed list from the server
            queued_jobs_list = self.queued_jobs[server_name]

            # Find the job in the active_jobs list
            for queued_job_id, queued_job_repo, queued_job_timestamp in queued_jobs_list:

                # If found
                if queued_job_repo == this_job_repo and queued_job_id == this_job_id:

                    # Remove the job from the active list
                    queued_jobs_list.remove((queued_job_id, queued_job_repo, queued_job_timestamp))

            # Overwrite the managed list
            self.queued_jobs[server_name] = queued_jobs_list

        # Log an update
        log(ctx, f"Acquired job slot", "debug", log_concurrency_status=True)

        return True


    def _get_server_semaphore(self, ctx: Context):
        """
        Get or create a semaphore for the given server.
        """

        server_name = ctx.job["job"]["server_name"]

        # Wait for the lock to be free
        with self.per_server_semaphores_lock:

            # self.per_server_semaphores dict keys are server_name
            # If the dict doesn't already have a semaphore in the dict
            if server_name not in self.per_server_semaphores:

                # Then create one
                # TODO: Get the limit for this server from the repos-to-convert.yaml file,
                # but not sure if this value can be changed without restarting the container
                self.per_server_semaphores[server_name] = multiprocessing.Semaphore(self.per_server_limit)

                # Can't log with log_concurrency_status=True, causes a deadlock
                log(ctx, f"Created concurrency limit semaphore for server {server_name} with limit {self.per_server_limit}", "debug")

        # Whether the server already had a semaphore in the dict, or one was just created for it, return the semaphore object
        return self.per_server_semaphores[server_name]


    def get_status(self, ctx: Context) -> dict:
        """
        Get current concurrency status for monitoring

        Called by log(), when log_concurrency_status=True is passed into log() calls
        """

        # Create status dict to be returned
        status = {
            "global": {
                "active": "",
                "available": "",
                "limit": self.global_limit
            },
            "servers": {},
            "active_jobs_count" : "",
            "active_jobs" : {},
            "queued_jobs_count": "",
            "queued_jobs": {},
        }

        active_jobs_count = 0
        queued_jobs_count = 0

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

                status["servers"][server_name] = {
                    "active":       self.per_server_limit - per_server_semaphore.get_value(),
                    "available":    per_server_semaphore.get_value(),
                    "limit":        self.per_server_limit,
                }

                if server_name not in self.active_jobs.keys():
                    continue

                # Get the lock on the active_jobs dict as well,
                # to ensure that the values are not changing as this is reading them
                # Not sure why to get and release the same lock for each server,
                # to ensure this function doesn't hold the lock for too long?
                with self.active_jobs_lock:

                    # The active jobs dict, seems to have the server hostname as keys
                    # Copy the dict, to free up the lock ASAP

                    active_jobs_list = self.active_jobs[server_name]

                    if len(active_jobs_list) > 0:

                        status_active_jobs_list = []

                        for active_job_id, active_job_repo, active_job_timestamp in active_jobs_list:

                            active_jobs_count += 1

                            status_active_jobs_list.append(
                                {
                                    "repo":                 active_job_repo,
                                    "id":                   active_job_id,
                                    "started_timestamp":    active_job_timestamp,
                                    "started_datetime":     datetime.fromtimestamp(active_job_timestamp),
                                    "running_time_seconds": int(time.time() - active_job_timestamp),
                                }
                            )

                        status["active_jobs"][server_name] = status_active_jobs_list

        status["active_jobs_count"] = active_jobs_count

        # Fill in details for queued jobs
        with self.queued_jobs_lock:

            # Check if manager is still alive before accessing shared objects
            # Why would self.manager not still be alive??? What shuts it down?
            if self.manager is None or self.manager._state.value != multiprocessing.managers.State.STARTED:
                log(ctx, "Yep", "debug")
                return status

            if len(self.queued_jobs.keys()) < 1:
                return status

# Process clone_svn_repo_crunch:
# Traceback (most recent call last):
#   File "/usr/lib/python3.10/multiprocessing/process.py", line 314, in _bootstrap
#     self.run()
#   File "/usr/lib/python3.10/multiprocessing/process.py", line 108, in run
#     self._target(*self._args, **self._kwargs)
#   File "/sourcegraph/repo-converter/src/utils/convert_repos.py", line 84, in conversion_wrapper
#     ctx.concurrency_manager.release_job_slot(ctx)
#   File "/sourcegraph/repo-converter/src/utils/concurrency.py", line 358, in release_job_slot
#     log(ctx, f"Released job slot", "debug", log_concurrency_status=True)
#   File "/sourcegraph/repo-converter/src/utils/log.py", line 46, in log
#     structured_payload = _build_structured_payload(
#   File "/sourcegraph/repo-converter/src/utils/log.py", line 114, in _build_structured_payload
#     payload["concurrency"] = ctx.concurrency_manager.get_status(ctx)
#   File "/sourcegraph/repo-converter/src/utils/concurrency.py", line 294, in get_status
#     for server_name in self.queued_jobs:
#   File "<string>", line 2, in __iter__
#   File "/usr/lib/python3.10/multiprocessing/managers.py", line 824, in _callmethod
#     proxytype = self._manager._registry[token.typeid][-1]
# AttributeError: 'NoneType' object has no attribute '_registry'

            for server_name in self.queued_jobs:

                queued_jobs_list = self.queued_jobs[server_name]

                if not isinstance(queued_jobs_list, list):
                    continue

                if len(queued_jobs_list) > 0:

                    status_queued_jobs_list = []

                    for queued_job_id, queued_job_repo, queued_job_timestamp in queued_jobs_list:

                        queued_jobs_count += 1

                        status_queued_jobs_list.append(
                            {
                                "repo":             queued_job_repo,
                                "id":               queued_job_id,
                                "queued_timestamp": queued_job_timestamp,
                                "queued_datetime":  datetime.fromtimestamp(queued_job_timestamp),
                                "queue_wait_time":  int(time.time() - queued_job_timestamp),
                            }
                        )

                    status["queued_jobs"][server_name] = status_queued_jobs_list

        status["queued_jobs_count"] = queued_jobs_count

        # Return the status dict
        return status


    def release_job_slot(self, ctx: Context) -> None:
        """Release both global and server-specific semaphores."""

        # Get job information from context
        this_job_id     = ctx.job["job"]["id"]
        this_job_repo   = ctx.job["job"]["repo_key"]
        server_name     = ctx.job["job"]["server_name"]

        try:

            with self.active_jobs_lock:

                # Read it into a normal list
                server_active_jobs_list = self.active_jobs[server_name]

                # Find the job in the active_jobs list
                for active_job_id, active_job_repo, active_job_timestamp in server_active_jobs_list:

                    # If found
                    if active_job_repo == this_job_repo and active_job_id == this_job_id:

                        # Release per-server semaphore
                        server_semaphore = self._get_server_semaphore(ctx)
                        server_semaphore.release()

                        # Release global semaphore
                        self.global_semaphore.release()

                        # Remove the job from the active list
                        server_active_jobs_list.remove((active_job_id, active_job_repo, active_job_timestamp))

                # Overwrite the managed list
                self.active_jobs[server_name] = server_active_jobs_list

            log(ctx, f"Released job slot", "debug", log_concurrency_status=True)

        except ValueError as e:
            log(ctx, f"Error releasing job slot: {e}", "error", log_concurrency_status=True)
