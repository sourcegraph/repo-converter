#!/usr/bin/env python3
# Status monitoring utility in a separate thread
# This can be a thread of the main.py module, to share the concurrency_manager's memory

# Import repo-converter modules
from utils.context import Context
from utils.logging import log
from utils import cmd

# Import Python standard modules
import threading
import time

def start(ctx: Context) -> None:
    """
    Start a background thread to periodically:
    - Print status updates on conversion jobs
    - Log concurrency status
    - Check on running processes
    """

    # Get the interval config from env vars
    interval = ctx.env_vars["STATUS_MONITOR_INTERVAL"]

    # If the env var is set to 0, then disable the monitor
    if interval <= 0:
        return

    def status_monitor_loop() -> None:

        while not ctx.shutdown_flag:

            cmd.status_update_and_cleanup_zombie_processes(ctx)

            # TODO: implement a conversion job status check, with number of commits added, svn config maxRev, etc.

            try:

                log(ctx, "Concurrency status", "debug", log_concurrency_status=True)

            except (BrokenPipeError, ConnectionResetError) as e:

                # These errors occur during shutdown when manager connections are closed
                log(ctx, f"Connection error in concurrency monitor (likely during shutdown)", "debug", exception=e)
                break

            except Exception as e:
                log(ctx, f"Exception in concurrency monitor", "error", exception=e)

            time.sleep(interval)


    monitor_thread = threading.Thread(target=status_monitor_loop, daemon=True, name="status_monitor")
    monitor_thread.start()

    # log(ctx, f"Started status monitor on {interval}s interval", "debug")
