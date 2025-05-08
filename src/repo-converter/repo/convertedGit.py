#!/usr/bin/env python3
# Handle repository operations for the resulting Git repos after conversion from other formats

from .base import Repo

class ConvertedGitRepo(Repo):
    """Class for Git repository operations."""

    def __init__(self):
        super().__init__()

    def gc(self):
        """Perform a Git garbage collection."""
        pass

    def delete(self):
        """Delete a Git repository once it's no longer in scope."""
        pass