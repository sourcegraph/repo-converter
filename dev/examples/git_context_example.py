#!/usr/bin/env python3
# Example usage of git context manager

from utils.git_context import git_operation_context
from utils.log import log
from utils.cmd import run_subprocess
from utils.context import Context

def example_git_sync(ctx: Context, repo_path: str):
    """Example function showing how to use git context manager"""

    # All logs within this context automatically include git metadata
    with git_operation_context(ctx, repo_path, "sync") as git_ctx:

        # This log will automatically include git metadata
        log(ctx, "Starting repository sync", "INFO")

        # Check if repo is up to date
        if git_ctx.get("repo_status") == "up_to_date":
            log(ctx, "Repository is already up to date", "INFO")
            return

        # Fetch latest changes - this subprocess call will also include git metadata
        log(ctx, "Fetching latest changes", "INFO")
        fetch_result = run_subprocess(ctx, ["git", "-C", repo_path, "fetch", "origin"])

        if fetch_result["success"]:
            log(ctx, "Fetch completed successfully", "INFO")

            # Try to merge changes
            log(ctx, "Merging changes", "INFO")
            merge_result = run_subprocess(ctx, ["git", "-C", repo_path, "merge", "origin/main"])

            if merge_result["success"]:
                log(ctx, "Sync completed successfully", "INFO")
            else:
                log(ctx, "Merge failed", "ERROR")
        else:
            log(ctx, "Fetch failed", "ERROR")

# Example of what the log output would look like:
"""
{
  "level": "INFO",
  "message": "Starting repository sync",
  "cycle": 1,
  "date": "2025-01-07",
  "time": "15:30:45.123456",
  "timestamp": 1736265045.1235,
  "code": {
    "module": "utils.git_context_example",
    "function": "example_git_sync",
    "file": "git_context_example.py",
    "line": 14
  },
  "container": {
    "uptime": "2h 15m 30s",
    "start_datetime": "2025-01-07T13:15:15.000000",
    "id": "abc123"
  },
  "image": {
    "build_tag": "v2.1.4",
    "build_date": "2025-01-07"
  },
  "git": {
    "repo_path": "/tmp/repos/my-repo",
    "operation": "sync",
    "repo_type": "git",
    "repo_key": "my-repo",
    "remote_url": "https://github.com/user/my-repo.git",
    "server_hostname": "github.com",
    "local_rev": "a1b2c3d4",
    "remote_rev": "e5f6g7h8",
    "commits_behind": 3,
    "repo_status": "out_of_date",
    "repo_size_mb": 45.7
  }
}
"""
