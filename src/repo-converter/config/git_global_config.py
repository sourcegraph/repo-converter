#!/usr/bin/env python3
# Git global config handling

from utils import cmd

def git_config_safe_directory():
    """Configure git to trust all directories."""

    cmd_git_safe_directory = ["git", "config", "--system", "--replace-all", "safe.directory", "\"*\""]

    cmd.run(cmd_git_safe_directory)

