#!/usr/bin/env python3
# Utility functions to handle signals

# Import repo-converter modules
from utils.log import log
from utils.context import Context
from utils import cmd

# Import Python standard modules
import os
import signal


def register_signal_handler(ctx: Context):

    try:

        signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(ctx, sig, frame))
        signal.signal(signal.SIGTERM, lambda sig, frame: signal_handler(ctx, sig, frame))
        signal.signal(signal.SIGCHLD, lambda sig, frame: sigchld_handler(ctx, sig, frame))

        # log(ctx, f"Registered signal handlers","debug")

    except Exception as exception:

        log(ctx, f"Registering signal handlers failed with exception: {type(exception)}, {exception.args}, {exception}","critical")


def signal_handler(ctx: Context, incoming_signal, frame) -> None:

    signal_name = signal.Signals(incoming_signal).name

    log(ctx, f"Received signal {signal_name} ({incoming_signal}), initiating graceful shutdown", "info")

    # Kill all child processes in our process group
    try:

        # Send SIGTERM to all processes in our group
        os.killpg(os.getpgid(os.getpid()), signal.SIGTERM)
        log(ctx, "Sent SIGTERM to process group", "info")

    except ProcessLookupError:
        log(ctx, "No process group to terminate", "debug")

    except OSError as e:
        log(ctx, f"Error terminating process group: {e}", "error")

    # Terminate any active multiprocessing jobs
    try:
        terminate_multiprocessing_jobs_on_shutdown(ctx, timeout=15)  # Shorter timeout during shutdown

    except Exception as e:
        log(ctx, f"Error during multiprocessing job termination: {e}", "error")

    # Clean up any remaining zombie processes
    cmd.status_update_and_cleanup_zombie_processes(ctx)

    # Exit gracefully
    log(ctx, f"Graceful shutdown complete for signal {signal_name}", "info")
    exit(0)


def sigchld_handler(ctx: Context, incoming_signal, frame) -> None:
    """Handle SIGCHLD to immediately reap zombie children"""

    # Reap all available zombie children without blocking
    while True:

        try:

            # WNOHANG means don't block if no children are ready
            # -1 means wait for any child process
            pid, status = os.waitpid(-1, os.WNOHANG)

            # If pid is 0, no more children are ready
            if pid == 0:
                break

            # log(ctx, f"SIGCHLD handler reaped child PID {pid} with status {status}", "debug")

            # Only log if child exited with non-zero status or was killed by signal
            if os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0:
                log(ctx, f"SIGCHLD handler reaped child PID {pid} with exit code {os.WEXITSTATUS(status)}", "warning")
            elif os.WIFSIGNALED(status):
                log(ctx, f"SIGCHLD handler reaped child PID {pid} killed by signal {os.WTERMSIG(status)}", "warning")

        except OSError:
            # No child processes exist or other error
            break

        except Exception as e:
            log(ctx, f"Error in SIGCHLD handler: {e}", "debug")
            break


def terminate_multiprocessing_jobs_on_shutdown(ctx: Context, timeout: int = 30) -> None:
    """Terminate all active multiprocessing jobs gracefully."""

    if not hasattr(ctx, 'active_repo_conversion_processes'):
        return

    log(ctx, f"Terminating {len(ctx.active_repo_conversion_processes)} active multiprocessing jobs", "info")

    for process, repo_key, server_hostname in ctx.active_repo_conversion_processes[:]:  # Copy list to avoid modification during iteration
        try:
            if process.is_alive():
                log(ctx, f"{repo_key}; Sending SIGTERM to multiprocessing job", "info")
                process.terminate()  # Send SIGTERM

                # Wait for graceful termination
                process.join(timeout=timeout)

                if process.is_alive():
                    log(ctx, f"{repo_key}; Force killing unresponsive multiprocessing job", "warning")
                    process.kill()  # Force kill with SIGKILL
                    process.join(timeout=5)  # Brief wait after kill

                if not process.is_alive():
                    log(ctx, f"{repo_key}; Successfully terminated multiprocessing job", "info")

                    # Remove job from list
                    ctx.active_repo_conversion_processes.remove((process, repo_key, server_hostname))

                else:
                    log(ctx, f"{repo_key}; Failed to terminate multiprocessing job", "error")

        except ProcessLookupError:

            log(ctx, f"{repo_key}; Multiprocessing job already terminated", "debug")
            # Remove from list since it's already gone
            ctx.active_repo_conversion_processes.remove((process, repo_key, server_hostname))

        except Exception as e:
            log(ctx, f"{repo_key}; Error terminating multiprocessing job: {e}", "error")
