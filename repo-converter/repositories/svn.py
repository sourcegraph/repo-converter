#!/usr/bin/env python3
# SVN repository handling

from .base import Repository

class SVNRepository(Repository):
    """Class for SVN repository operations."""
    
    def __init__(self):
        super().__init__()
    
    def clone(self):
        """Clone an SVN repository."""
        pass
    
    def update(self):
        """Update an SVN repository."""
        pass