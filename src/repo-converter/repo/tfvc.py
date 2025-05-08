#!/usr/bin/env python3
# TFVC repository handling

from .base import Repo

class TFVCRepo(Repo):
    """Class for TFVC repository operations."""

    def __init__(self):
        super().__init__()

    def clone(self):
        """Clone a TFVC repository."""
        raise NotImplementedError("TFVC clone not implemented yet")

    def update(self):
        """Update a TFVC repository."""
        raise NotImplementedError("TFVC update not implemented yet")