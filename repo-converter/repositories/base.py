#!/usr/bin/env python3
# Base Repository class

class Repository:
    """Base class for repository operations."""
    
    def __init__(self):
        pass
        
    def clone(self):
        """Clone the repository."""
        raise NotImplementedError("Subclasses must implement clone()")
        
    def update(self):
        """Update the repository."""
        raise NotImplementedError("Subclasses must implement update()")