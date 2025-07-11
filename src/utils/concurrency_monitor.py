#!/usr/bin/env python3
# Monitoring utility for concurrency management
# This can be a thread of the main.py module, to share the concurrency_manager's memory

# Import repo-converter modules
from utils.context import Context
from utils.log import log

# Import Python standard modules
import threading
import time

def start_concurrency_monitor(ctx: Context) -> None:
    """Start a background thread to log concurrency status periodically."""

    # Get the interval config from env vars
    interval = ctx.env_vars["CONCURRENCY_MONITOR_INTERVAL"]

    # If the env var is set to 0, then disable the monitor
    if interval <= 0:
        return

    def concurrency_monitor_loop() -> None:

        while not ctx.shutdown_flag:

            try:

                log(ctx, f"Concurrency status", "debug", log_concurrency_status=True)

            except (BrokenPipeError, ConnectionResetError) as exception:
                # These errors occur during shutdown when manager connections are closed
                log(ctx, f"Connection error in concurrency monitor (likely during shutdown): {exception}", "debug")
                break

            except Exception as exception:
                log(ctx, f"Error in concurrency monitor: {exception}", "error")

                raise exception

            time.sleep(interval)


    monitor_thread = threading.Thread(target=concurrency_monitor_loop, daemon=True, name="concurrency_monitor")
    monitor_thread.start()

    # log(ctx, f"Started concurrency monitor on {interval}s interval", "debug")
