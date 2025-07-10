#!/usr/bin/env python3
# Concurrency manager class, to limit the number of concurrent repo conversion jobs
# Only one instance of this class should exist, in main.py's initialization steps

# Need to be careful with log(..., log_concurrency_status=True), as then the log module calls the get_status() function in this class and creates a deadlock

# Import repo-converter modules
from http import server
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

    def __init__(self, ctx: Context):

        # Create member attributes with shorter names
        self.global_limit = ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_GLOBAL"]
        self.per_server_limit = ctx.env_vars["MAX_CONCURRENT_CONVERSIONS_PER_SERVER"]

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
        self.active_jobs = self.manager.dict() # server_name -> list of (repo_key, timestamp, correlation_id)

        # Ensure no two processes can write to active_jobs at the same
        self.active_jobs_lock = multiprocessing.Lock()

        # Track jobs waiting for a semaphore to become available, using a list for each server_name, not sure why
        self.job_queue = self.manager.dict()  # server_name -> list of (repo_key, timestamp, correlation_id)
        self.job_queue_lock = multiprocessing.Lock()

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
        correlation_id  = ctx.job["job"]["correlation_id"]
        repo_key        = ctx.job["job"]["repo_key"]
        server_name     = ctx.job["job"]["server_name"]

        ## Check if this repo already has a job in progress
        # TODO: Remove the duplicate logic in svn.py, and integrate the missing bits in here
        with self.active_jobs_lock:

            # active_jobs is a dict, with subdicts for each server_name, which contains a list of active jobs for that server
            if server_name in self.active_jobs:

                server_active_jobs_list = list(self.active_jobs[server_name])

                if any(repo == repo_key for repo, timestamp, correlation in server_active_jobs_list):

                    log(ctx, f"Skipping; Repo job already in progress; repo: {repo_key}, timestamp: {timestamp}; correlation_id: {correlation}", "info", ctx.job, correlation_id)
                    return False

        ## Add this job to the dict of waiting jobs, just in case the blocking semaphore acquire takes a while
        with self.job_queue_lock:

            if server_name not in self.job_queue:
                self.job_queue[server_name] = self.manager.list()

            jobs_queued_list = list(self.job_queue[server_name])
            jobs_queued_list.append((repo_key, time.time(), correlation_id))

            self.job_queue[server_name] = jobs_queued_list

        ## Check per-server limit
        # Get the semaphore object for this server
        server_semaphore = self._get_server_semaphore(ctx)

        # Check the semaphore value for number of remaining slots
        if server_semaphore.get_value() <= 0:
            log(ctx, f"Hit per-server concurrency limit; MAX_CONCURRENT_CONVERSIONS_PER_SERVER={self.per_server_limit}, waiting for a server slot", "info", ctx.job, log_concurrency_status=True)

        ## Check global limit
        if self.global_semaphore.get_value() <= 0:
            log(ctx, f"Hit global concurrency limit; MAX_CONCURRENT_CONVERSIONS_GLOBAL={self.global_limit}, waiting for a slot", "info", ctx.job, log_concurrency_status=True)

        ## Acquire a slot in the the server-specific semaphore
        # Want to block, so that the main loop has to wait until all repos get a chance to run through before finishing
        # TODO: Determine if this would build an infinite queue of jobs, ballooning memory usage, if job execution time is longer than REPO_CONVERTER_INTERVAL_SECONDS
        if not server_semaphore.acquire(block=True):

            log(ctx, f"server_semaphore.acquire failed", "error", ctx.job, correlation_id)
            return False

        ## Acquire a slot in the the global semaphore
        # Want to block, so that the main loop has to wait until all repos get a chance to run through before finishing
        # TODO: Determine if this would build an infinite queue of jobs, ballooning memory usage, if job execution time is longer than REPO_CONVERTER_INTERVAL_SECONDS
        if not self.global_semaphore.acquire(block=True):

            # Release the server semaphore since we couldn't get the global one
            server_semaphore.release()

            log(ctx, f"self.global_semaphore.acquire failed", "error", ctx.job, correlation_id)
            return False

        ## Successfully acquired both semaphores

        # Add the active job to the active_jobs dict
        with self.active_jobs_lock:

            # If the server doesn't already have a list, then create one
            if server_name not in self.active_jobs:
                self.active_jobs[server_name] = self.manager.list()

            # Read it into a normal list
            server_active_jobs_list = list(self.active_jobs[server_name])

            # Append the repo job
            server_active_jobs_list.append((repo_key, time.time(), correlation_id))

            # Assign the list back to the manager list
            self.active_jobs[server_name] = server_active_jobs_list

        # Remove the job from the queued jobs list
        with self.job_queue_lock:

            jobs_queued_list = list(self.job_queue[server_name])
            jobs_queued_list = [(repo, timestamp, correlation) for repo, timestamp, correlation in jobs_queued_list if repo != repo_key and correlation != correlation_id]
            self.job_queue[server_name] = jobs_queued_list

        # Log an update
        log(ctx, f"Acquired job slot", "debug", ctx.job, correlation_id)

        return True


    def _get_server_semaphore(self, ctx: Context):
        """
        Get or create a semaphore for the given server.
        """

        correlation_id  = ctx.job["job"]["correlation_id"]
        server_name     = ctx.job["job"]["server_name"]

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
        log(ctx, f"Created concurrency limit semaphore for server {server_name} with limit {self.per_server_limit}", "debug", ctx.job, correlation_id, log_concurrency_status=True)

        # Whether the server already had a semaphore in the dict, or one was just created for it, return the semaphore object
        return self.per_server_semaphores[server_name]


    def get_status(self, ctx: Context) -> dict:
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
            "servers": {},
            "active_jobs_count" : "",
            "active_jobs" : {},
            "job_queue_count": "",
            "job_queue": {},
        }

        active_jobs_count = 0
        job_queue_count = 0

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
                    "active": self.per_server_limit - per_server_semaphore.get_value(),
                    "available": per_server_semaphore.get_value(),
                    "limit": self.per_server_limit,
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

                    active_jobs_list = list(self.active_jobs[server_name])

                    if len(active_jobs_list) > 0:

                        status_active_jobs_list = list()

                        for repo, timestamp, correlation_id in active_jobs_list:

                            active_jobs_count += 1

                            status_active_jobs_list.append(
                                {
                                    "repo": repo,
                                    "correlation_id": correlation_id,
                                    "started_timestamp": "%.4f" % timestamp,
                                    "started_datetime": datetime.fromtimestamp(timestamp),
                                    "running_time_seconds": "%.4f" % (time.time() - timestamp),
                                }
                            )

                        status["active_jobs"][server_name] = status_active_jobs_list

        status["active_jobs_count"] = active_jobs_count

        # Fill in details for queued jobs
        with self.job_queue_lock:

            for server_name in self.job_queue:

                jobs_queued_list = list(self.job_queue[server_name])

                if len(jobs_queued_list) > 0:

                    status_jobs_queued_list = list()

                    for repo, timestamp, correlation_id in jobs_queued_list:

                        job_queue_count += 1
                        timestamp = round(timestamp,2)

                        status_jobs_queued_list.append(
                            {
                                "repo": repo,
                                "correlation_id": correlation_id,
                                "queued_timestamp": timestamp,
                                "queued_datetime": datetime.fromtimestamp(timestamp),
                                "queue_wait_time": round((time.time() - timestamp),2),
                            }
                        )

                    status["job_queue"][server_name] = status_jobs_queued_list

        status["job_queue_count"] = job_queue_count

        # Return the status dict
        return status


    def release_job_slot(self, ctx: Context):
        """Release both global and server-specific semaphores."""

        # Get job information from context
        correlation_id  = ctx.job["job"]["correlation_id"]
        repo_key        = ctx.job["job"]["repo_key"]
        server_name     = ctx.job["job"]["server_name"]

        try:

            with self.active_jobs_lock:

                # Read it into a normal list
                server_active_jobs_list = list(self.active_jobs[server_name])

                # Find the job in the active_jobs list
                for repo, timestamp, correlation in server_active_jobs_list:

                    # If found
                    if repo == repo_key and correlation == correlation_id:

                        # Release per-server semaphore
                        server_semaphore = self._get_server_semaphore(ctx)
                        server_semaphore.release()

                        # Release global semaphore
                        self.global_semaphore.release()

                        # Remove the job from the active list
                        server_active_jobs_list.remove((repo, timestamp, correlation_id))

                # Overwrite the managed list
                self.active_jobs[server_name] = server_active_jobs_list

            log(ctx, f"Released job slot", "debug", ctx.job, correlation_id)

        except ValueError as e:
            log(ctx, f"Error releasing job slot: {e}", "error", ctx.job, correlation_id)
