#!/usr/bin/env python3
# Git operation context manager for automatic metadata injection

# Import repo-converter modules
from utils.log import log
from utils.context import Context
from utils.cmd import run_subprocess

# Import Python standard modules
from contextlib import contextmanager
from typing import Optional, Dict, Any
import os
import subprocess

# Import third party modules
import structlog


class GitContextManager:
    """Context manager for git operations that automatically injects repo metadata"""

    def __init__(self):
        self.context_stack = []
        self.logger = structlog.get_logger()

    def push_context(self, context_data: Dict[str, Any]) -> None:
        """Push context data onto the stack"""
        self.context_stack.append(context_data)

    def pop_context(self) -> Optional[Dict[str, Any]]:
        """Pop context data from the stack"""
        if self.context_stack:
            return self.context_stack.pop()
        return None

    def get_merged_context(self) -> Dict[str, Any]:
        """Get all context data merged together"""
        merged = {}
        for context in self.context_stack:
            merged.update(context)
        return merged


# Global instance
git_context_manager = GitContextManager()


@contextmanager
def git_operation_context(ctx: Context, repo_path: str, operation: str):
    """
    Context manager that automatically injects git repository metadata into all logs.

    Args:
        ctx: Context object
        repo_path: Path to the git repository
        operation: Operation being performed (e.g., "sync", "clone", "fetch")

    Yields:
        Dict containing git metadata

    Example:
        with git_operation_context(ctx, "/tmp/repos/my-repo", "sync") as git_ctx:
            # All logs within this block automatically include git metadata
            log(ctx, "Starting sync operation", "INFO")
            run_subprocess(ctx, ["git", "fetch"])
    """

    # Capture git repository metadata
    git_metadata = _inspect_git_repo(ctx, repo_path, operation)

    # Push context to the stack
    git_context_manager.push_context(git_metadata)

    try:
        yield git_metadata
    finally:
        # Always clean up context
        git_context_manager.pop_context()


def _inspect_git_repo(ctx: Context, repo_path: str, operation: str) -> Dict[str, Any]:
    """
    Inspect a git repository and extract metadata for logging context.

    Args:
        ctx: Context object
        repo_path: Path to the git repository
        operation: Operation being performed

    Returns:
        Dict containing git repository metadata
    """

    git_metadata = {
        "repo_path": repo_path,
        "operation": operation,
        "repo_type": "git"
    }

    # Only proceed if the path exists and is a git repository
    if not os.path.exists(repo_path):
        git_metadata["repo_status"] = "not_found"
        return git_metadata

    git_dir = os.path.join(repo_path, ".git")
    if not os.path.exists(git_dir):
        git_metadata["repo_status"] = "not_git_repo"
        return git_metadata

    try:
        # Get repo key (basename of the repo path)
        git_metadata["repo_key"] = os.path.basename(repo_path)

        # Get remote URL
        remote_url = _get_git_remote_url(ctx, repo_path)
        if remote_url:
            git_metadata["remote_url"] = remote_url
            git_metadata["server_hostname"] = _extract_hostname_from_url(remote_url)

        # Get current revision
        local_rev = _get_git_revision(ctx, repo_path)
        if local_rev:
            git_metadata["local_rev"] = local_rev

        # Get remote revision (if we can fetch it)
        remote_rev = _get_git_remote_revision(ctx, repo_path)
        if remote_rev:
            git_metadata["remote_rev"] = remote_rev

            # Calculate commits behind
            if local_rev and remote_rev and local_rev != remote_rev:
                commits_behind = _count_commits_behind(ctx, repo_path, local_rev, remote_rev)
                git_metadata["commits_behind"] = commits_behind
                git_metadata["repo_status"] = "out_of_date" if commits_behind > 0 else "up_to_date"
            else:
                git_metadata["repo_status"] = "up_to_date"
        else:
            git_metadata["repo_status"] = "unknown"

        # Get repository size information
        repo_size = _get_repo_size(repo_path)
        if repo_size:
            git_metadata["repo_size_mb"] = repo_size

    except Exception as e:
        # Log error but don't fail the context
        log(ctx, f"Error inspecting git repo {repo_path}: {str(e)}", "WARNING")
        git_metadata["repo_status"] = "error"
        git_metadata["error_message"] = str(e)

    return git_metadata


def _get_git_remote_url(ctx: Context, repo_path: str) -> Optional[str]:
    """Get the remote URL for the git repository"""
    try:
        result = run_subprocess(
            ctx,
            ["git", "-C", repo_path, "remote", "get-url", "origin"],
            quiet=True
        )
        if result["success"] and result["output"]:
            return result["output"][0].strip()
    except Exception:
        pass
    return None


def _get_git_revision(ctx: Context, repo_path: str) -> Optional[str]:
    """Get the current HEAD revision"""
    try:
        result = run_subprocess(
            ctx,
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            quiet=True
        )
        if result["success"] and result["output"]:
            return result["output"][0].strip()[:8]  # Short hash
    except Exception:
        pass
    return None


def _get_git_remote_revision(ctx: Context, repo_path: str) -> Optional[str]:
    """Get the remote HEAD revision"""
    try:
        result = run_subprocess(
            ctx,
            ["git", "-C", repo_path, "rev-parse", "origin/HEAD"],
            quiet=True
        )
        if result["success"] and result["output"]:
            return result["output"][0].strip()[:8]  # Short hash
    except Exception:
        pass
    return None


def _count_commits_behind(ctx: Context, repo_path: str, local_rev: str, remote_rev: str) -> int:
    """Count how many commits the local branch is behind the remote"""
    try:
        result = run_subprocess(
            ctx,
            ["git", "-C", repo_path, "rev-list", "--count", f"{local_rev}..{remote_rev}"],
            quiet=True
        )
        if result["success"] and result["output"]:
            return int(result["output"][0].strip())
    except Exception:
        pass
    return 0


def _extract_hostname_from_url(url: str) -> Optional[str]:
    """Extract hostname from a git URL"""
    try:
        if url.startswith("https://"):
            return url.split("https://")[1].split("/")[0]
        elif url.startswith("git@"):
            return url.split("git@")[1].split(":")[0]
        elif url.startswith("ssh://"):
            return url.split("ssh://")[1].split("/")[0]
    except Exception:
        pass
    return None


def _get_repo_size(repo_path: str) -> Optional[int]:
    """Get repository size in MB"""
    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(repo_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
        return round(total_size / (1024 * 1024), 1)  # Convert to MB
    except Exception:
        pass
    return None


def get_current_git_context() -> Dict[str, Any]:
    """Get the current git context for manual use"""
    return git_context_manager.get_merged_context()
