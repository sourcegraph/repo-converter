#!/usr/bin/env python3
# Status monitoring utility in a separate thread
# This can be a thread of the main.py module, to share the concurrency_manager's memory

# Import repo-converter modules
from utils.context import Context
from utils.log import log
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

            try:

                log(ctx, "Concurrency status", "debug", log_concurrency_status=True)

            except (BrokenPipeError, ConnectionResetError) as exception:
                # These errors occur during shutdown when manager connections are closed
                log(ctx, f"Connection error in concurrency monitor (likely during shutdown): {exception}", "debug")
                break

            except Exception as exception:
                log(ctx, f"Error in concurrency monitor: {exception}", "error")

                raise exception

            time.sleep(interval)


    monitor_thread = threading.Thread(target=status_monitor_loop, daemon=True, name="status_monitor")
    monitor_thread.start()

    # log(ctx, f"Started status monitor on {interval}s interval", "debug")
