#!/usr/bin/env python3
# Monitoring utility for concurrency management
# This can be a thread of the main.py module, to share the concurrency_manager's memory

# Import repo-converter modules
from utils.concurrency import ConcurrencyManager
from utils.context import Context
from utils.log import log

# Import Python standard modules
import threading
import time

def start_concurrency_monitor(ctx: Context, concurrency_manager: ConcurrencyManager) -> None:
    """Start a background thread to log concurrency status periodically."""

    # Get the interval config from env vars
    interval = ctx.env_vars["CONCURRENCY_MONITOR_INTERVAL"]

    # If the env var is set to 0, then disable the monitor
    if interval <= 0:
        return

    def monitor_loop() -> None:

        while True:

            try:

                # Get the status from the shared instance of ConcurrencyManager
                status = concurrency_manager.get_status()

                # Get the global stats
                global_active = status["global"]["active_slots"]
                global_limit = status["global"]["limit"]

                # Build the array for per-server stats
                server_summary = []

                # Get the hostname and status dict from the servers dict, within the get_status dict
                for server_hostname, server_status in status["servers"].items():

                    server_active = server_status["active_slots"]
                    server_limit = server_status["limit"]
                    active_jobs = list(server_status["active_jobs"])

                    if server_active > 0:

                        server_summary.append(f"{server_hostname}: {server_active}/{server_limit}; Count of repos: {len(active_jobs)}; Repos: {active_jobs}")

                servers_str = ", ".join(server_summary) if server_summary else "none active"

                # 2025-06-17; 07:27:32.000558; af75882; run 1; INFO; Concurrency status - Global: 11/100, Servers: svn.apache.org: 10/10
                log(ctx, f"Concurrency status - Global: {global_active}/{global_limit}, Servers: {servers_str}", "info")

            except Exception as e:
                log(ctx, f"Error in concurrency monitor: {e}", "error")

            time.sleep(interval)

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True, name="concurrency_monitor")
    monitor_thread.start()

    log(ctx, f"Concurrency status - Started concurrency monitor with {interval}s interval", "info")
